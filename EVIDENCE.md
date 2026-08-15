# Evidence

One pasted proof per Definition-of-Done checkbox (§ 6 of the brief).
All outputs below are real, captured from `docker compose exec api pytest tests/ -v`
and live runs on 15 Aug 2026.

---

## METERING

**A billable action creates exactly one usage event, even under retries —
deduplicated by idempotency key. A test proves double-counting cannot happen.**

```
tests/test_idempotency.py::test_retry_same_key_creates_one_event_and_mirrors_response PASSED
tests/test_idempotency.py::test_concurrent_retries_create_one_event PASSED
tests/test_idempotency.py::test_different_keys_create_separate_events PASSED
tests/test_idempotency.py::test_missing_idempotency_key_rejected PASSED
```

The concurrent test fires 5 identical requests simultaneously; the DB's
`UNIQUE (tenant_id, idempotency_key)` constraint (migrations/001_init.sql)
guarantees a single recorded event — dedup is enforced at the database
level, not by a racy application-level check. The retried request mirrors
the original response exactly (same request_id), proven by
`test_retry_same_key_creates_one_event_and_mirrors_response`.

---

## QUOTAS

**Usage is checked against the tenant's plan; requests over the limit are
rejected. Responses carry the correct status codes (429 / 402) and a
message explaining why.**

```
tests/test_quota.py::test_call_at_exact_limit_allowed_then_next_rejected PASSED
tests/test_quota.py::test_token_quota_rejects_overage_with_429 PASSED
tests/test_quota.py::test_inactive_subscription_gets_402 PASSED
tests/test_quota.py::test_retry_at_limit_still_mirrors_original_response PASSED
```

Documented boundary rule: a request is allowed if `used + requested <= limit`.
On the Free plan (1,000 calls) call #1000 succeeds and call #1001 returns
**429** with `{error, usage_type, used, limit, requested, message}` in the
body. An inactive (canceled) subscription returns **402** with a
payment-required message. A retry of the request that consumed the last
unit of quota still mirrors its original response instead of 429ing —
a retry is the same request, not new usage.

---

## COST CALCULATION

**Monthly usage rolls up into a cost figure per tenant. AI token pricing
handles cached input tokens, reasoning tokens, and output pricing
correctly. Pricing constants are pinned and covered by tests.**

```
tests/test_cost.py::test_pinned_total_one_million_of_each_bucket_is_exactly_925_cents PASSED
tests/test_cost.py::test_cached_input_is_cheaper_than_fresh_input PASSED
tests/test_cost.py::test_reasoning_tokens_billed_at_output_rate PASSED
tests/test_cost.py::test_categories_cannot_simply_be_added PASSED
tests/test_cost.py::test_rounding_happens_once_at_rollup_not_per_event PASSED
tests/test_cost.py::test_usage_endpoint_reports_pinned_cost PASSED
```

Pinned rates live in `app/pricing.py` only; all math is integer
micro-cents (1/1,000,000 cent), rounded to cents exactly once at rollup.
Pinned totals: 1M of each bucket = exactly **925 cents** ($1.00 input +
$0.25 cached + $4.00 output + $4.00 reasoning-billed-as-output).
`test_categories_cannot_simply_be_added` proves bucket costs are summed,
never token counts ($5.00 correct vs $2.00 naive). `GET /usage` returns
`{ used, limit, cost }` per tenant for the current month, verified
end-to-end by `test_usage_endpoint_reports_pinned_cost` (93 cents).

---

## STRIPE INTEGRATION

**Subscription checkout works end-to-end in Stripe test mode. Webhooks
verify signatures, ignore duplicate events, and update tenant plan/status.**

```
tests/test_webhooks.py::test_forged_signature_rejected_with_400_and_nothing_changes PASSED
tests/test_webhooks.py::test_valid_checkout_event_flips_tenant_free_to_pro PASSED
tests/test_webhooks.py::test_replayed_event_processed_once PASSED
tests/test_webhooks.py::test_subscription_deleted_cancels_and_generate_returns_402 PASSED
```

A forged webhook (wrong signing secret) returns **400** and changes
nothing — not even a webhook_events row. A replayed event (same evt_ id,
valid signature) is answered **200** but processed once: the event id is
the table's PRIMARY KEY, so the replay's insert fails and processing is
skipped. Cancellation propagates: after `customer.subscription.deleted`,
the billable endpoint answers **402**.

**Live end-to-end checkout, verified 15 Aug 2026:** `POST /checkout` →
Stripe test-mode Checkout (card 4242 4242 4242 4242) →
`checkout.session.completed` delivered via Stripe CLI listener → tenant
flipped free → pro live → `GET /usage` response:

```json
{
  "plan": "pro",
  "subscription_status": "active",
  "api_calls":  { "used": 24,    "limit": 100000 },
  "ai_tokens":  { "used": 15600, "limit": 10000000 },
  "cost":       { "cents": 4,    "formatted": "$0.04" }
}
```

---

## DATA MODEL, TESTS & DOCUMENTATION

**Database includes tenants, plans, subscriptions, and usage events;
customer data isolated per tenant.**
Schema as append-only migrations: `migrations/001_init.sql` (five tables,
CHECK constraints, the UNIQUE idempotency constraint, usage rollup index),
`002_response_snapshot.sql`, `003_token_breakdown.sql`. Every usage event,
subscription, and quota check is keyed by tenant_id; tests create their
own tenants and never observe each other's data.

**Tests cover: duplicate usage prevention, quota boundary cases
(at / just under / over), cost calculations, invalid webhook rejection,
duplicate-webhook handling.**
Full suite, all green:

```
============================ 18 passed in 4.76s ============================
```

**README + architecture diagram + setup instructions; submission-pack
files present.**
README.md (run/test/API/architecture/limitations) · DESIGN.md (schema,
API surface, layers, non-goal) · capstone.yaml · EVIDENCE.md (this file) ·
BUILDLOG.md · .env.example.
