"""CostService — convert usage events into money.

All arithmetic in integer micro-cents (see app/pricing.py). Rounding
to cents happens exactly once, at the end of the monthly rollup —
never per event, so many small events can't each round up.
"""
from app.db import get_conn
from app.pricing import API_CALL_RATE, TOKEN_RATES, micro_cents_to_cents


def token_event_cost_micro(quantity: int, breakdown: dict | None) -> int:
    """Cost of one ai_tokens event in micro-cents.

    With a breakdown, each bucket is priced at its own rate and the
    COSTS are summed (never the token counts — rule 3). Without one
    (simple `tokens` requests), the whole quantity is priced
    conservatively at the fresh-input rate.
    """
    if breakdown:
        return sum(
            int(breakdown.get(bucket, 0)) * rate
            for bucket, rate in TOKEN_RATES.items()
        )
    return quantity * TOKEN_RATES["input_tokens"]


def monthly_rollup(tenant_id: str) -> dict:
    """used / limit / cost for the current month — the GET /usage payload."""
    with get_conn() as conn:
        sub = conn.execute(
            """
            SELECT p.api_call_limit, p.ai_token_limit, p.id AS plan_id, s.status
            FROM subscriptions s JOIN plans p ON p.id = s.plan_id
            WHERE s.tenant_id = %s
            ORDER BY s.updated_at DESC LIMIT 1
            """,
            (tenant_id,),
        ).fetchone()
        events = conn.execute(
            """
            SELECT usage_type, quantity, token_breakdown
            FROM usage_events
            WHERE tenant_id = %s AND created_at >= date_trunc('month', now())
            """,
            (tenant_id,),
        ).fetchall()

    calls_used = 0
    tokens_used = 0
    total_micro = 0
    for ev in events:
        if ev["usage_type"] == "api_call":
            calls_used += ev["quantity"]
            total_micro += ev["quantity"] * API_CALL_RATE
        else:
            tokens_used += ev["quantity"]
            total_micro += token_event_cost_micro(ev["quantity"], ev["token_breakdown"])

    cost_cents = micro_cents_to_cents(total_micro)
    return {
        "plan": sub["plan_id"] if sub else None,
        "subscription_status": sub["status"] if sub else None,
        "api_calls": {
            "used": calls_used,
            "limit": sub["api_call_limit"] if sub else None,
        },
        "ai_tokens": {
            "used": tokens_used,
            "limit": sub["ai_token_limit"] if sub else None,
        },
        "cost": {
            "cents": cost_cents,
            "formatted": f"${cost_cents // 100}.{cost_cents % 100:02d}",
        },
    }
