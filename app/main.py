import uuid

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.db import run_migrations
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
    tenant_id: uuid.UUID
    tokens: int | None = Field(default=None, gt=0)


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

    try:
        check_quota(tenant_id, body.tokens)
    except PaymentRequired as e:
        raise HTTPException(status_code=402, detail=e.detail)
    except QuotaExceeded as e:
        raise HTTPException(status_code=429, detail=e.detail)

    response = {
        "result": "simulated ai response",
        "tokens_used": body.tokens or 0,
        "request_id": str(uuid.uuid4()),
    }

    try:
        record_usage(tenant_id, body.tokens, idempotency_key, response)
        return response
    except DuplicateRequest as dup:
        return dup.original_response
