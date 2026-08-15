"""QuotaService — enforce plan limits BEFORE the billable action.

Boundary rule (documented, tested, probed):
    a request is allowed if used + requested <= limit.
So a Free tenant's 1,000th API call succeeds; the 1,001st gets 429.

Status-code semantics:
    429 Too Many Requests  -> active plan, usage quota exhausted
    402 Payment Required   -> subscription not active (canceled/lapsed)

These are domain exceptions, not HTTP responses: the service layer
stays HTTP-free, and the route maps them to status codes.
"""
from app.db import get_conn


class QuotaExceeded(Exception):
    def __init__(self, usage_type: str, used: int, limit: int, requested: int):
        self.detail = {
            "error": "quota_exceeded",
            "usage_type": usage_type,
            "used": used,
            "limit": limit,
            "requested": requested,
            "message": (
                f"{usage_type} quota exceeded: {used} used of {limit} this month; "
                f"request for {requested} more was rejected. "
                "Upgrade your plan or wait for the monthly reset."
            ),
        }


class PaymentRequired(Exception):
    def __init__(self, status: str):
        self.detail = {
            "error": "payment_required",
            "subscription_status": status,
            "message": (
                f"Subscription is '{status}', not active. "
                "Complete payment or renew your subscription to continue."
            ),
        }


def _plan_and_usage(tenant_id: str):
    with get_conn() as conn:
        sub = conn.execute(
            """
            SELECT s.status, p.api_call_limit, p.ai_token_limit
            FROM subscriptions s JOIN plans p ON p.id = s.plan_id
            WHERE s.tenant_id = %s
            ORDER BY s.updated_at DESC LIMIT 1
            """,
            (tenant_id,),
        ).fetchone()
        usage = conn.execute(
            """
            SELECT usage_type, COALESCE(SUM(quantity), 0) AS used
            FROM usage_events
            WHERE tenant_id = %s AND created_at >= date_trunc('month', now())
            GROUP BY usage_type
            """,
            (tenant_id,),
        ).fetchall()
    used = {row["usage_type"]: row["used"] for row in usage}
    return sub, used.get("api_call", 0), used.get("ai_tokens", 0)


def check_quota(tenant_id: str, tokens: int | None):
    """Raise PaymentRequired / QuotaExceeded, or return silently if allowed."""
    sub, calls_used, tokens_used = _plan_and_usage(tenant_id)

    if sub is None or sub["status"] != "active":
        raise PaymentRequired(sub["status"] if sub else "missing")

    if calls_used + 1 > sub["api_call_limit"]:
        raise QuotaExceeded("api_calls", calls_used, sub["api_call_limit"], 1)

    if tokens and tokens_used + tokens > sub["ai_token_limit"]:
        raise QuotaExceeded("ai_tokens", tokens_used, sub["ai_token_limit"], tokens)
