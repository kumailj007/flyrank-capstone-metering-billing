import uuid

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.db import run_migrations
from app.services.meter import DuplicateRequest, record_usage, tenant_exists

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
    records usage idempotently. (Quota check arrives in Stage 4.)"""
    tenant_id = str(body.tenant_id)
    if not tenant_exists(tenant_id):
        raise HTTPException(status_code=404, detail="Unknown tenant")

    response = {
        "result": "simulated ai response",
        "tokens_used": body.tokens or 0,
        "request_id": str(uuid.uuid4()),
    }

    try:
        record_usage(tenant_id, body.tokens, idempotency_key, response)
        return response
    except DuplicateRequest as dup:
        # Retry detected: mirror the original response, record nothing.
        return dup.original_response
