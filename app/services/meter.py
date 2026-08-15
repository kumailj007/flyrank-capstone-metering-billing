"""MeterService — idempotent usage recording.

The idempotency guarantee does NOT come from checking "does this key
exist?" in Python first. Two concurrent retries could both pass that
check and both insert. Instead we simply INSERT and let the database's
UNIQUE (tenant_id, idempotency_key) constraint decide: the second
insert raises UniqueViolation, which we translate into "return the
original response". Correct by construction.

get_original_response() exists as a fast path so routes can detect a
retry BEFORE running quota checks — a retry of a request that already
succeeded must mirror the original response even if the tenant has
since reached their limit. It is an optimization only; the UNIQUE
constraint remains the real guarantee under concurrency.
"""
import json

from psycopg.errors import UniqueViolation

from app.db import get_conn


class DuplicateRequest(Exception):
    """Raised when this idempotency key was already processed.

    Carries the original response so the caller can mirror it."""

    def __init__(self, original_response):
        self.original_response = original_response


def get_original_response(tenant_id: str, idempotency_key: str):
    """Return the stored response for this key, or None if unseen."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT response_snapshot FROM usage_events
            WHERE tenant_id = %s AND idempotency_key = %s
            """,
            (tenant_id, idempotency_key),
        ).fetchone()
    return row["response_snapshot"] if row else None


def record_usage(tenant_id: str, tokens: int | None, idempotency_key: str, response: dict):
    """Record one api_call event (+ one ai_tokens event if tokens given),
    atomically, deduplicated by idempotency key.

    Both inserts happen in one transaction: the connection context
    manager commits on success and rolls back on exception, so a
    duplicate can never leave a half-written pair of events.

    The token event's key gets a ':tokens' suffix so both rows can
    coexist under the UNIQUE (tenant_id, idempotency_key) constraint
    while still being tied to the same client key.
    """
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO usage_events
                    (tenant_id, usage_type, quantity, idempotency_key, response_snapshot)
                VALUES (%s, 'api_call', 1, %s, %s)
                """,
                (tenant_id, idempotency_key, json.dumps(response)),
            )
            if tokens:
                conn.execute(
                    """
                    INSERT INTO usage_events
                        (tenant_id, usage_type, quantity, idempotency_key)
                    VALUES (%s, 'ai_tokens', %s, %s)
                    """,
                    (tenant_id, tokens, f"{idempotency_key}:tokens"),
                )
    except UniqueViolation:
        raise DuplicateRequest(get_original_response(tenant_id, idempotency_key))


def tenant_exists(tenant_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM tenants WHERE id = %s", (tenant_id,)
        ).fetchone()
    return row is not None
