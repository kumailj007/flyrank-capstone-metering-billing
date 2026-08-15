"""Pinned pricing tests — exact expected totals, integer math only.

If anyone touches app/pricing.py, these numbers break loudly.

Unit tests hit the cost functions directly; the last test proves the
full pipeline: POST /generate with a breakdown -> GET /usage cost.
    docker compose exec api pytest tests/test_cost.py -v
"""
import uuid

import httpx

from app.db import get_conn
from app.pricing import micro_cents_to_cents
from app.services.cost import token_event_cost_micro

BASE = "http://localhost:8000"


# ---------- pinned unit tests (no HTTP, deterministic) ----------

def test_pinned_total_one_million_of_each_bucket_is_exactly_925_cents():
    """1M input ($1.00) + 1M cached ($0.25) + 1M output ($4.00)
    + 1M reasoning ($4.00, billed as output) = $9.25 exactly."""
    breakdown = {
        "input_tokens": 1_000_000,
        "cached_input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "reasoning_tokens": 1_000_000,
    }
    micro = token_event_cost_micro(4_000_000, breakdown)
    assert micro_cents_to_cents(micro) == 925


def test_cached_input_is_cheaper_than_fresh_input():
    fresh = token_event_cost_micro(0, {"input_tokens": 1_000_000})
    cached = token_event_cost_micro(0, {"cached_input_tokens": 1_000_000})
    assert cached == fresh // 4          # pinned: 25% of input rate
    assert cached < fresh


def test_reasoning_tokens_billed_at_output_rate():
    reasoning = token_event_cost_micro(0, {"reasoning_tokens": 500_000})
    output = token_event_cost_micro(0, {"output_tokens": 500_000})
    assert reasoning == output


def test_categories_cannot_simply_be_added():
    """Pricing 2M mixed tokens at any single rate gives the WRONG total —
    the buckets must be priced separately and their COSTS summed."""
    breakdown = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    correct = token_event_cost_micro(2_000_000, breakdown)
    naive_all_input = token_event_cost_micro(2_000_000, None)  # input rate
    assert correct != naive_all_input
    assert micro_cents_to_cents(correct) == 500      # $1 + $4 = $5.00
    assert micro_cents_to_cents(naive_all_input) == 200   # $2.00 (wrong)


def test_rounding_happens_once_at_rollup_not_per_event():
    """3 tokens at the input rate = 300 micro-cents = 0.0003 cents.
    Rounded per-event that would be 0; the rollup keeps micro-cents."""
    one = token_event_cost_micro(0, {"input_tokens": 3})
    assert one == 300                    # micro-cents preserved
    assert micro_cents_to_cents(one) == 0  # rounds only at the end


# ---------- integration: /generate breakdown -> /usage cost ----------

def _make_tenant() -> str:
    with get_conn() as conn:
        tid = conn.execute(
            "INSERT INTO tenants (name) VALUES (%s) RETURNING id",
            (f"cost-test-{uuid.uuid4()}",),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO subscriptions (tenant_id, plan_id) VALUES (%s, 'pro')",
            (tid,),
        )
    return str(tid)


def test_usage_endpoint_reports_pinned_cost():
    """100k of each bucket + 1 api call:
    tokens: (0.10 + 0.025 + 0.40 + 0.40) = $0.925 -> 92.5c
    call:   $0.001 -> 0.1c
    total:  92.6c -> rounds to 93 cents."""
    t = _make_tenant()
    r = httpx.post(
        f"{BASE}/generate",
        json={
            "tenant_id": t,
            "input_tokens": 100_000,
            "cached_input_tokens": 100_000,
            "output_tokens": 100_000,
            "reasoning_tokens": 100_000,
        },
        headers={"Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert r.status_code == 200

    u = httpx.get(f"{BASE}/usage", params={"tenant_id": t}).json()
    assert u["api_calls"]["used"] == 1
    assert u["ai_tokens"]["used"] == 400_000
    assert u["cost"]["cents"] == 93
    assert u["cost"]["formatted"] == "$0.93"
