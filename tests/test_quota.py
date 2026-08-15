"""Boundary honesty: at / just under / over the limit, plus 402.

Runs against the live API inside the container:
    docker compose exec api pytest tests/test_quota.py -v
"""
import uuid

import httpx

from app.db import get_conn

BASE = "http://localhost:8000"


def _make_tenant(plan: str = "free", status: str = "active") -> str:
    with get_conn() as conn:
        tid = conn.execute(
            "INSERT INTO tenants (name) VALUES (%s) RETURNING id",
            (f"quota-test-{uuid.uuid4()}",),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO subscriptions (tenant_id, plan_id, status) VALUES (%s, %s, %s)",
            (tid, plan, status),
        )
    return str(tid)


def _set_calls_used(tenant_id: str, n: int):
    """Bulk-fill this month's api_call usage to n."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO usage_events (tenant_id, usage_type, quantity, idempotency_key)
            VALUES (%s, 'api_call', %s, %s)
            """,
            (tenant_id, n, f"bulk-{uuid.uuid4()}"),
        )


def _gen(tenant_id: str, tokens=None):
    body = {"tenant_id": tenant_id}
    if tokens:
        body["tokens"] = tokens
    return httpx.post(
        f"{BASE}/generate",
        json=body,
        headers={"Idempotency-Key": f"test-{uuid.uuid4()}"},
    )


def test_call_at_exact_limit_allowed_then_next_rejected():
    """Free plan: 1,000 calls. Call #1000 succeeds; #1001 -> 429."""
    t = _make_tenant()
    _set_calls_used(t, 999)

    at_boundary = _gen(t)          # used 999 + 1 = 1000 <= 1000
    assert at_boundary.status_code == 200

    over = _gen(t)                 # used 1000 + 1 = 1001 > 1000
    assert over.status_code == 429
    detail = over.json()["detail"]
    assert detail["error"] == "quota_exceeded"
    assert detail["used"] == 1000
    assert detail["limit"] == 1000
    assert "message" in detail


def test_token_quota_rejects_overage_with_429():
    """Free plan: 100k tokens. A request pushing past it -> 429."""
    t = _make_tenant()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO usage_events (tenant_id, usage_type, quantity, idempotency_key)
            VALUES (%s, 'ai_tokens', 99999, %s)
            """,
            (t, f"bulk-{uuid.uuid4()}"),
        )

    ok = _gen(t, tokens=1)         # 99,999 + 1 = 100,000 <= 100,000
    assert ok.status_code == 200

    over = _gen(t, tokens=2)       # 100,000 + 2 > 100,000
    assert over.status_code == 429
    assert over.json()["detail"]["usage_type"] == "ai_tokens"


def test_inactive_subscription_gets_402():
    t = _make_tenant(status="canceled")
    r = _gen(t)
    assert r.status_code == 402
    detail = r.json()["detail"]
    assert detail["error"] == "payment_required"
    assert detail["subscription_status"] == "canceled"


def test_retry_at_limit_still_mirrors_original_response():
    """A retry of the request that consumed the LAST unit of quota must
    mirror the original response, not get a 429 — same request, not new
    usage."""
    t = _make_tenant()
    _set_calls_used(t, 999)
    key = f"test-{uuid.uuid4()}"
    body = {"tenant_id": t}
    headers = {"Idempotency-Key": key}

    first = httpx.post(f"{BASE}/generate", json=body, headers=headers)
    assert first.status_code == 200   # this was call #1000

    retry = httpx.post(f"{BASE}/generate", json=body, headers=headers)
    assert retry.status_code == 200   # mirrored, NOT 429
    assert retry.json() == first.json()
