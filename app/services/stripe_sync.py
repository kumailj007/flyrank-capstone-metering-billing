"""StripeSync — payment truth lives at Stripe; our DB mirrors it
through VERIFIED, DEDUPLICATED events only.

Two independent defenses, in order:

1. Signature verification. Anyone on the internet can POST JSON to a
   public webhook URL claiming "payment complete". Stripe signs every
   delivery (Stripe-Signature header, HMAC over timestamp + raw body);
   we verify with the whsec_ secret before trusting a byte. Forgeries
   -> InvalidSignature -> the route answers 400 and nothing changes.

2. Replay dedup. Stripe retries deliveries it thinks failed, so the
   same event can arrive twice. webhook_events uses STRIPE'S event id
   (evt_...) as PRIMARY KEY: the first insert wins, the replay's
   insert violates the PK and is ignored — same correct-by-construction
   pattern as usage metering. We still answer 200 to a replay, because
   2xx is what tells Stripe to stop resending.

Dedup insert + state change share one transaction: an event is marked
processed if and only if its effect committed.

Version note (BUILDLOG-worthy): stripe-python 15.x changed the parsed
event object's dict behavior (`.get` raised AttributeError). We now
verify the signature with WebhookSignature.verify_header — the actual
security step — and parse the raw payload with json.loads ourselves:
plain dicts, version-proof.
"""
import json
import os

import stripe
from psycopg.errors import UniqueViolation

from app.db import get_conn

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PRO_PRICE_ID = os.environ.get("STRIPE_PRO_PRICE_ID", "")


class InvalidSignature(Exception):
    pass


def verify_and_parse(payload: bytes, sig_header: str):
    """Verify the signature, then return the event as plain dicts.

    Verification needs the RAW request body — re-serialized JSON would
    produce a different byte string and always fail the HMAC check.
    We verify first (the security step), then json.loads the payload
    ourselves: plain dicts are version-proof, while the Stripe
    library's object wrapper changed dict behavior across versions.
    """
    try:
        stripe.WebhookSignature.verify_header(
            payload.decode("utf-8"), sig_header, WEBHOOK_SECRET, tolerance=300
        )
    except Exception as e:
        raise InvalidSignature(str(e))
    return json.loads(payload)


def process_event(event) -> str:
    """Apply a verified event exactly once. Returns 'processed' or
    'duplicate'."""
    obj = event["data"]["object"]
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO webhook_events (id, event_type) VALUES (%s, %s)",
                (event["id"], event["type"]),
            )

            if event["type"] == "checkout.session.completed":
                # client_reference_id carries OUR tenant id through
                # Stripe's checkout and back — that's the join key.
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET plan_id = 'pro', status = 'active',
                        stripe_customer_id = %s,
                        stripe_subscription_id = %s,
                        updated_at = now()
                    WHERE tenant_id = %s
                    """,
                    (obj.get("customer"), obj.get("subscription"),
                     obj.get("client_reference_id")),
                )

            elif event["type"] == "customer.subscription.updated":
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET status = %s, updated_at = now()
                    WHERE stripe_subscription_id = %s
                    """,
                    (obj.get("status"), obj.get("id")),
                )

            elif event["type"] == "customer.subscription.deleted":
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET status = 'canceled', updated_at = now()
                    WHERE stripe_subscription_id = %s
                    """,
                    (obj.get("id"),),
                )
            # Unknown event types: recorded in webhook_events, no action.
    except UniqueViolation:
        return "duplicate"
    return "processed"


def create_checkout_session(tenant_id: str) -> str:
    """Create a test-mode Checkout session for the Pro plan; return its URL."""
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": PRO_PRICE_ID, "quantity": 1}],
        client_reference_id=tenant_id,
        success_url="http://localhost:8000/checkout/success",
        cancel_url="http://localhost:8000/checkout/cancel",
    )
    return session.url