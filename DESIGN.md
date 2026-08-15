# Design — Usage Metering & Billing Engine

## Problem statement

A multi-tenant SaaS backend must answer: how much has each customer used,
what does it cost, and have they hit their plan limits? This service meters
usage idempotently, enforces quotas with honest status codes, converts
usage to cost with real AI-token pricing rules, and mirrors subscription
state from Stripe via verified, deduplicated webhooks.

## Data model

### tenants

id          UUID  PK
name        TEXT
created_at  TIMESTAMPTZ

### plans

id                  TEXT PK        -- 'free', 'pro'
api_call_limit      INTEGER        -- free: 1,000   · pro: 100,000
ai_token_limit      INTEGER        -- free: 100,000 · pro: 10,000,000

### subscriptions

id                      UUID PK
tenant_id               UUID FK → tenants
plan_id                 TEXT FK → plans
status                  TEXT           -- 'active', 'canceled'
stripe_customer_id      TEXT NULL
stripe_subscription_id  TEXT NULL
updated_at              TIMESTAMPTZ

### usage_events

id               UUID PK
tenant_id        UUID FK → tenants
usage_type       TEXT      -- 'api_call' | 'ai_tokens'
quantity         INTEGER   -- 1 for a call; token count for tokens
idempotency_key  TEXT NOT NULL
created_at       TIMESTAMPTZ
UNIQUE (tenant_id, idempotency_key)

-- The UNIQUE constraint makes double-counting impossible at the DB level:
-- two concurrent retries cannot both insert; the second fails and we
-- return the original result.

### webhook_events

id            TEXT PK        -- Stripe's event ID, e.g. 'evt_1Nab...'
event_type    TEXT           -- 'checkout.session.completed', etc.
processed_at  TIMESTAMPTZ

-- The PK is the dedup: a replayed Stripe event has the same evt_ ID,
-- so the second insert fails and processing is skipped (still 200).

## API surface

POST /generate            -- the dummy billable endpoint
  Header: Idempotency-Key (required)
  Body: { tenant_id, tokens? }
  → records usage event(s), checks quota, returns simulated result + cost
  → 429 if usage quota exceeded, 402 if plan/payment blocks it
  → same Idempotency-Key retried = same response, no new event
  -- The key comes from the client because only the client knows a
  -- retry is a retry; the server just sees two requests.

GET /usage?tenant_id=...  -- the read path
  → { api_calls: {used, limit}, ai_tokens: {used, limit}, cost_cents }
  for the current month

POST /checkout            -- start upgrade
  Body: { tenant_id }
  → creates Stripe Checkout session (test mode), returns the URL

POST /webhooks/stripe     -- Stripe's callback
  → verify signature (bad → 400), dedupe by event id, update plan/status

GET /health               -- liveness probe for the evaluator

## Layers

HTTP layer (FastAPI routes)     -- parse/validate requests, map results to status codes
  ↓
Service layer (business logic)  -- MeterService, QuotaService, CostService, StripeSync
  ↓
Data layer (Postgres)           -- migrations, queries, constraints

Rule: routes never contain business logic; services never build HTTP responses.
The DB enforces what must never break (idempotency, dedup) via constraints.

## Non-goal

No invoicing, proration, or overage billing. Requests over quota are
rejected, never billed. (These are stretch goals, out of core scope.)