"""Shared requirement #3 evidence: the background job corrects drift
between our database and Stripe, retries transient failures, and
survives one bad record.

Stripe is stubbed with monkeypatch — deterministic, no network.
Every stub is SCOPED to the test's own subscription id and answers
'active' (a no-op) for anything else in the database: an unscoped
stub here once canceled the real demo tenants by running the job
against the whole DB with "everything is canceled" as the answer.
    docker compose exec api pytest tests/test_reconcile.py -v
"""
import uuid

import stripe

from app.db import get_conn
from jobs import reconcile as job


def _make_tenant_with_sub(status: str, stripe_sub_id: str) -> str:
    with get_conn() as conn:
        tid = conn.execute(
            "INSERT INTO tenants (name) VALUES (%s) RETURNING id",
            (f"rec-test-{uuid.uuid4()}",),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO subscriptions (tenant_id, plan_id, status, stripe_subscription_id)
            VALUES (%s, 'pro', %s, %s)
            """,
            (tid, status, stripe_sub_id),
        )
    return str(tid)


def _local_status(stripe_sub_id: str) -> str:
    with get_conn() as conn:
        return conn.execute(
            "SELECT status FROM subscriptions WHERE stripe_subscription_id = %s",
            (stripe_sub_id,),
        ).fetchone()["status"]


def test_missed_cancellation_is_fixed(monkeypatch):
    """The exact drift observed live in this build: Stripe knows the
    truth, our DB missed the webhook. The job repairs it. Stub scoped
    to this test's sub; every other sub answers 'active' (no-op)."""
    sub_id = f"sub_rec_{uuid.uuid4().hex[:12]}"
    _make_tenant_with_sub("active", sub_id)              # local says active
    monkeypatch.setattr(
        stripe.Subscription, "retrieve",
        staticmethod(lambda sid: {"status": "canceled"} if sid == sub_id
                     else {"status": "active"}),
    )

    summary = job.reconcile()

    assert _local_status(sub_id) == "canceled"
    assert summary["fixed"] >= 1


def test_matching_state_left_untouched(monkeypatch):
    sub_id = f"sub_rec_{uuid.uuid4().hex[:12]}"
    _make_tenant_with_sub("active", sub_id)
    monkeypatch.setattr(
        stripe.Subscription, "retrieve",
        staticmethod(lambda sid: {"status": "active"}),
    )

    job.reconcile()

    assert _local_status(sub_id) == "active"


def test_transient_failures_retried_then_succeed(monkeypatch):
    """First two calls for OUR sub blow up like a flaky network; the
    third answers. The retry loop must deliver the answer, not the
    exception. Other subscriptions in the DB (left by other tests)
    answer immediately and aren't counted."""
    sub_id = f"sub_rec_{uuid.uuid4().hex[:12]}"
    _make_tenant_with_sub("active", sub_id)
    calls = {"n": 0}

    def flaky(sid):
        if sid != sub_id:
            return {"status": "active"}   # other tests' subs: not ours to count
        calls["n"] += 1
        if calls["n"] < 3:
            raise stripe.error.APIConnectionError("network blip")
        return {"status": "canceled"}

    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(flaky))
    monkeypatch.setattr(job, "BACKOFF_SECONDS", 0)   # keep the test fast

    job.reconcile()

    assert calls["n"] == 3
    assert _local_status(sub_id) == "canceled"


def test_one_dead_record_does_not_stop_the_rest(monkeypatch):
    """A job running into one permanently failing record must log it,
    count it, and still reconcile everything else."""
    bad_id = f"sub_rec_bad_{uuid.uuid4().hex[:8]}"
    good_id = f"sub_rec_good_{uuid.uuid4().hex[:8]}"
    _make_tenant_with_sub("active", bad_id)
    _make_tenant_with_sub("active", good_id)

    def selective(sid):
        if sid == bad_id:
            raise stripe.error.APIConnectionError("permanently down")
        return {"status": "canceled"} if sid == good_id else {"status": "active"}

    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(selective))
    monkeypatch.setattr(job, "BACKOFF_SECONDS", 0)

    summary = job.reconcile()

    assert summary["failed"] >= 1                      # the bad one counted
    assert _local_status(good_id) == "canceled"        # the good one still fixed
    assert _local_status(bad_id) == "active"           # untouched, not corrupted
