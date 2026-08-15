"""Probe 4 territory: forged webhooks rejected, replays processed once.

We sign test payloads with the SAME whsec_ secret the app verifies
against (from .env), using Stripe's documented scheme:
    Stripe-Signature: t=<unix ts>,v1=HMAC_SHA256(secret, "<ts>.<raw body>")
No network, fully deterministic.

    docker compose exec api pytest tests/test_webhooks.py -v
"""
import hashlib
import hmac
import json
import os
import time
import uuid

import httpx

from app.db import get_conn

BASE = "http://localhost:8000"
SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]


def _sign(payload: bytes, secret: str) -> str:
    t = int(time.time())
    mac = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256)
    return f"t={t},v1={mac.hexdigest()}"


def _make_tenant() -> str:
    with get_conn() as conn:
        tid = conn.execute(
            "INSERT INTO tenants (name) VALUES (%s) RETURNING id",
            (f"wh-test-{uuid.uuid4()}",),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO subscriptions (tenant_id, plan_id) VALUES (%s, 'free')",
            (tid,),
        )
    return str(tid)


def _plan(tenant_id: str):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT plan_id, status, stripe_subscription_id FROM subscriptions
            WHERE tenant_id = %s ORDER BY updated_at DESC LIMIT 1
            """,
            (tenant_id,),
        ).fetchone()


def _checkout_event(tenant_id: str, event_id: str, sub_id: str) -> bytes:
    return json.dumps({
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {
            "client_reference_id": tenant_id,
            "customer": f"cus_{uuid.uuid4().hex[:14]}",
            "subscription": sub_id,
        }},
    }).encode()


def _post(payload: bytes, sig: str):
    return httpx.post(
        f"{BASE}/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": sig, "content-type": "application/json"},
    )


def test_forged_signature_rejected_with_400_and_nothing_changes():
    t = _make_tenant()
    payload = _checkout_event(t, f"evt_forged_{uuid.uuid4().hex}", "sub_x")

    r = _post(payload, _sign(payload, "whsec_wrong_secret"))

    assert r.status_code == 400
    assert _plan(t)["plan_id"] == "free"          # untouched
    with get_conn() as conn:
        n = conn.execute(
            "SELECT count(*) AS n FROM webhook_events WHERE id LIKE 'evt_forged_%'"
        ).fetchone()["n"]
    assert n == 0                                  # not even recorded


def test_valid_checkout_event_flips_tenant_free_to_pro():
    t = _make_tenant()
    assert _plan(t)["plan_id"] == "free"
    sub_id = f"sub_{uuid.uuid4().hex[:14]}"
    payload = _checkout_event(t, f"evt_{uuid.uuid4().hex}", sub_id)

    r = _post(payload, _sign(payload, SECRET))

    assert r.status_code == 200
    assert r.json()["status"] == "processed"
    row = _plan(t)
    assert row["plan_id"] == "pro"
    assert row["status"] == "active"
    assert row["stripe_subscription_id"] == sub_id


def test_replayed_event_processed_once():
    t = _make_tenant()
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = _checkout_event(t, event_id, f"sub_{uuid.uuid4().hex[:14]}")
    sig = _sign(payload, SECRET)

    first = _post(payload, sig)
    replay = _post(payload, sig)

    assert first.json()["status"] == "processed"
    assert replay.status_code == 200               # 200 so Stripe stops retrying
    assert replay.json()["status"] == "duplicate"
    with get_conn() as conn:
        n = conn.execute(
            "SELECT count(*) AS n FROM webhook_events WHERE id = %s", (event_id,)
        ).fetchone()["n"]
    assert n == 1


def test_subscription_deleted_cancels_and_generate_returns_402():
    """End to end: upgrade via webhook, cancel via webhook, then the
    billable endpoint answers 402 — the full payment-sync loop."""
    t = _make_tenant()
    sub_id = f"sub_{uuid.uuid4().hex[:14]}"

    up = _checkout_event(t, f"evt_{uuid.uuid4().hex}", sub_id)
    _post(up, _sign(up, SECRET))
    assert _plan(t)["plan_id"] == "pro"

    deleted = json.dumps({
        "id": f"evt_{uuid.uuid4().hex}",
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": sub_id, "status": "canceled"}},
    }).encode()
    _post(deleted, _sign(deleted, SECRET))

    assert _plan(t)["status"] == "canceled"
    r = httpx.post(
        f"{BASE}/generate",
        json={"tenant_id": t},
        headers={"Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert r.status_code == 402
