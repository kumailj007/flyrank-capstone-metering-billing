"""The heart of the capstone: prove double-counting cannot happen.

Runs against the live API inside the container:
    docker compose exec api pytest tests/test_idempotency.py -v
"""
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.db import get_conn

BASE = "http://localhost:8000"


def _tenant_id():
    with get_conn() as conn:
        return str(conn.execute("SELECT id FROM tenants LIMIT 1").fetchone()["id"])


def _event_count(tenant_id, key):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT count(*) AS n FROM usage_events
            WHERE tenant_id = %s AND idempotency_key IN (%s, %s)
            """,
            (tenant_id, key, f"{key}:tokens"),
        ).fetchone()["n"]


def test_retry_same_key_creates_one_event_and_mirrors_response():
    tenant = _tenant_id()
    key = f"test-{uuid.uuid4()}"
    body = {"tenant_id": tenant, "tokens": 2500}
    headers = {"Idempotency-Key": key}

    r1 = httpx.post(f"{BASE}/generate", json=body, headers=headers)
    r2 = httpx.post(f"{BASE}/generate", json=body, headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    # The retry mirrors the original response exactly (same request_id).
    assert r1.json() == r2.json()
    # Exactly one api_call event + one ai_tokens event — not two of each.
    assert _event_count(tenant, key) == 2


def test_concurrent_retries_create_one_event():
    """Five identical requests fired at once: the DB constraint, not a
    Python check, must guarantee a single recorded event."""
    tenant = _tenant_id()
    key = f"test-{uuid.uuid4()}"
    body = {"tenant_id": tenant, "tokens": 100}
    headers = {"Idempotency-Key": key}

    def fire(_):
        return httpx.post(f"{BASE}/generate", json=body, headers=headers)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(fire, range(5)))

    assert all(r.status_code == 200 for r in results)
    assert _event_count(tenant, key) == 2  # one api_call + one ai_tokens


def test_different_keys_create_separate_events():
    tenant = _tenant_id()
    k1, k2 = f"test-{uuid.uuid4()}", f"test-{uuid.uuid4()}"
    body = {"tenant_id": tenant}

    httpx.post(f"{BASE}/generate", json=body, headers={"Idempotency-Key": k1})
    httpx.post(f"{BASE}/generate", json=body, headers={"Idempotency-Key": k2})

    assert _event_count(tenant, k1) == 1
    assert _event_count(tenant, k2) == 1


def test_missing_idempotency_key_rejected():
    tenant = _tenant_id()
    r = httpx.post(f"{BASE}/generate", json={"tenant_id": tenant})
    assert r.status_code == 422
