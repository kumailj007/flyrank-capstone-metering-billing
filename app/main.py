import uuid

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.db import run_migrations
from app.services.cost import monthly_rollup
from app.services.meter import (
    DuplicateRequest,
    get_original_response,
    record_usage,
    tenant_exists,
)
from app.services.quota import PaymentRequired, QuotaExceeded, check_quota

app = FastAPI(title="Usage Metering & Billing Engine")


@app.on_event("startup")
def startup():
    run_migrations()


@app.get("/health")
def health():
    return {"status": "ok"}


class GenerateRequest(BaseModel):
    """Either a simple total (`tokens`) or a per-category breakdown.

    With a breakdown, the quota-relevant total is the SUM of all four
    buckets (reasoning tokens consume quota too), and cost is computed
    per bucket at its own rate.
    """

    tenant_id: uuid.UUID
    tokens: int | None = Field(default=None, gt=0)
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def simple_xor_breakdown(self):
        breakdown_sum = (
            self.input_tokens
            + self.cached_input_tokens
            + self.output_tokens
            + self.reasoning_tokens
        )
        if self.tokens and breakdown_sum:
            raise ValueError("Provide either `tokens` or a breakdown, not both")
        return self

    @property
    def total_tokens(self) -> int:
        return self.tokens or (
            self.input_tokens
            + self.cached_input_tokens
            + self.output_tokens
            + self.reasoning_tokens
        )

    @property
    def breakdown(self) -> dict | None:
        if self.tokens:
            return None
        b = {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }
        return b if any(b.values()) else None


@app.post("/generate")
def generate(body: GenerateRequest, idempotency_key: str = Header(..., min_length=1)):
    """The dummy billable endpoint: simulates an AI generation,
    enforces quota, records usage idempotently.

    Order matters:
      1. Retry fast path — a request that already succeeded must
         mirror its original response, even if the tenant has since
         hit their limit. A retry is the same request, not new usage.
      2. Quota check — reject over-limit NEW requests with 429/402
         BEFORE any usage is recorded.
      3. Record — the UNIQUE constraint remains the concurrency-safe
         dedup guarantee underneath the fast path.
    """
    tenant_id = str(body.tenant_id)
    if not tenant_exists(tenant_id):
        raise HTTPException(status_code=404, detail="Unknown tenant")

    original = get_original_response(tenant_id, idempotency_key)
    if original is not None:
        return original

    total = body.total_tokens
    try:
        check_quota(tenant_id, total or None)
    except PaymentRequired as e:
        raise HTTPException(status_code=402, detail=e.detail)
    except QuotaExceeded as e:
        raise HTTPException(status_code=429, detail=e.detail)

    response = {
        "result": "simulated ai response",
        "tokens_used": total,
        "request_id": str(uuid.uuid4()),
    }

    try:
        record_usage(
            tenant_id, total or None, idempotency_key, response, body.breakdown
        )
        return response
    except DuplicateRequest as dup:
        return dup.original_response


@app.get("/usage")
def usage(tenant_id: uuid.UUID):
    """The read path: { used, limit, cost } for the current month."""
    tid = str(tenant_id)
    if not tenant_exists(tid):
        raise HTTPException(status_code=404, detail="Unknown tenant")
    return monthly_rollup(tid)
