"""HTTP layer for the payment-sync path. Business logic lives in
app/services/stripe_sync.py; these routes only parse, delegate, and
map results to status codes."""
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.meter import tenant_exists
from app.services.stripe_sync import (
    InvalidSignature,
    create_checkout_session,
    process_event,
    verify_and_parse,
)

router = APIRouter()


class CheckoutRequest(BaseModel):
    tenant_id: uuid.UUID


@router.post("/checkout")
def checkout(body: CheckoutRequest):
    tid = str(body.tenant_id)
    if not tenant_exists(tid):
        raise HTTPException(status_code=404, detail="Unknown tenant")
    url = create_checkout_session(tid)
    return {"checkout_url": url}


@router.get("/checkout/success")
def checkout_success():
    return {"message": "Checkout complete — the webhook will sync your plan."}


@router.get("/checkout/cancel")
def checkout_cancel():
    return {"message": "Checkout canceled — no changes made."}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()          # RAW body — required for HMAC
    sig = request.headers.get("stripe-signature", "")
    try:
        event = verify_and_parse(payload, sig)
    except InvalidSignature:
        raise HTTPException(status_code=400, detail="Invalid signature")
    result = process_event(event)
    return {"status": result, "event_id": event["id"]}
