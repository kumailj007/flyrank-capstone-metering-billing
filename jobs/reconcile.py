"""Reconciliation job — nightly comparison of our database against
Stripe's view. Catches missed webhooks.

Why this exists (observed live during this build): a Stripe test
payment completed while the local webhook listener was down. Stripe
said "pro"; our database still said "free". Webhooks are delivery
attempts, not guarantees — a background job that periodically asks
Stripe for the truth is how billing systems self-heal.

Design (shared requirement #3: work off the request path, retries,
failure alert):
- Runs outside any HTTP request — invoked by a scheduler (compose
  service here; cron/Inngest/Celery in production).
- Per-subscription transient failures are retried with backoff.
- A subscription that still fails after retries is logged loudly and
  counted; the job continues with the rest (one bad record must not
  stop reconciliation of the others).
- If Stripe is unreachable entirely, the job exits non-zero with a
  FAILURE ALERT line — that exit code is what a scheduler alerts on.

Run once:      docker compose exec api python -m jobs.reconcile
Run scheduled: docker compose --profile jobs up reconciler -d
"""
import logging
import os
import sys
import time

import stripe

from app.db import get_conn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reconcile")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

MAX_RETRIES = 3
BACKOFF_SECONDS = 2

# Stripe subscription statuses that mean the tenant should keep access.
ACTIVE_LIKE = {"active", "trialing"}


def _fetch_with_retries(sub_id: str):
    """Fetch one subscription from Stripe, retrying transient failures.

    Retries: network errors, rate limits, 5xx. Does NOT retry
    InvalidRequestError (e.g. the subscription doesn't exist) — that is
    a real answer, not a transient failure.
    """
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return stripe.Subscription.retrieve(sub_id)
        except stripe.error.InvalidRequestError:
            raise
        except Exception as exc:  # APIConnectionError, RateLimitError, APIError
            last_exc = exc
            log.warning(
                "transient failure fetching %s (attempt %d/%d): %s",
                sub_id, attempt, MAX_RETRIES, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SECONDS * attempt)
    raise last_exc


def reconcile() -> dict:
    """Compare every Stripe-linked subscription against Stripe's view.

    Returns a summary dict: {checked, fixed, missing, failed}.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, tenant_id, status, stripe_subscription_id
            FROM subscriptions
            WHERE stripe_subscription_id IS NOT NULL
            """
        ).fetchall()

    summary = {"checked": 0, "fixed": 0, "missing": 0, "failed": 0}

    for row in rows:
        summary["checked"] += 1
        sub_id = row["stripe_subscription_id"]
        try:
            remote = _fetch_with_retries(sub_id)
            remote_status = remote["status"]
        except stripe.error.InvalidRequestError:
            # Stripe has no such subscription: treat as canceled.
            remote_status = "canceled"
            summary["missing"] += 1
            log.warning("subscription %s not found at Stripe; marking canceled", sub_id)
        except Exception as exc:
            summary["failed"] += 1
            log.error("giving up on %s after %d retries: %s", sub_id, MAX_RETRIES, exc)
            continue

        local_status = row["status"]
        # Map Stripe's statuses onto our two: active-like stays active,
        # everything else (canceled, past_due, unpaid, ...) is stored as-is
        # so quota checks (which require 'active') deny access.
        desired = "active" if remote_status in ACTIVE_LIKE else remote_status

        if desired != local_status:
            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE subscriptions
                    SET status = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (desired, row["id"]),
                )
            summary["fixed"] += 1
            log.info(
                "reconciled tenant %s: local '%s' -> Stripe '%s'",
                row["tenant_id"], local_status, desired,
            )

    log.info("reconcile summary: %s", summary)
    return summary


def main() -> int:
    try:
        summary = reconcile()
    except Exception as exc:
        # Stripe (or the DB) unreachable as a whole — the loud failure.
        log.critical("FAILURE ALERT: reconciliation aborted: %s", exc)
        return 1
    # Per-record failures also surface in the exit code so a scheduler
    # can alert, while the log shows the job otherwise completed.
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
