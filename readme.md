# FlyRank Capstone — Usage Metering & Billing Engine

A backend service that meters usage, enforces subscription quotas,
calculates costs (including AI token pricing rules), and syncs plans
via Stripe (test mode) with signature-verified, idempotent webhooks.

**Stack:** Python · FastAPI · PostgreSQL (Docker) · Stripe test mode

## Status

✅ Core complete: idempotent metering, quota enforcement (429/402),
pinned cost engine, `GET /usage`, Stripe test-mode checkout + verified,
deduplicated webhooks. **18 tests green.** Live free→pro upgrade via
webhook verified end-to-end. Build history in [BUILDLOG.md](BUILDLOG.md);
proof per Definition-of-Done checkbox in [EVIDENCE.md](EVIDENCE.md).

## Run

```bash
git clone https://github.com/kumailj007/flyrank-capstone-metering-billing.git
cd flyrank-capstone-metering-billing
copy .env.example .env        # cp on Mac/Linux — then add your Stripe test keys
docker compose up --build -d
docker compose exec api python seed.py    # prints two demo tenant IDs
```

API at http://localhost:8000 · Swagger at http://localhost:8000/docs

## Test

```bash
docker compose exec api pytest tests/ -v
```

18 tests: idempotency (incl. concurrent retries), quota boundaries
(at / just under / over the limit, 429 and 402), pinned pricing
(cached-input and reasoning-token rules, exact expected totals), and
webhooks (forged → 400, replay → processed once, cancel → 402).

## Stripe setup (test mode only — no card, no real money, ever)

1. Stripe sandbox account → Secret key (`sk_test_...`) → `.env`
2. Product "Pro Plan", recurring monthly → its **price** ID
   (`price_...`, not `prod_...`) → `.env`
3. Webhook delivery via Stripe CLI (run through Docker — no install):

```bash
docker run --rm -it -v stripe-config:/root/.config/stripe stripe/stripe-cli login
docker run --rm -it -v stripe-config:/root/.config/stripe stripe/stripe-cli listen --forward-to host.docker.internal:8000/webhooks/stripe
```

The `listen` command prints the `whsec_...` signing secret → `.env`.
Keep that window running; it is the webhook delivery pipe.
Test card for Checkout: `4242 4242 4242 4242`, any future expiry, any CVC.

## API

| Method | Path              | What it does                                                |
| ------ | ----------------- | ----------------------------------------------------------- |
| POST   | /generate         | Dummy billable endpoint — idempotent metering + quota check |
| GET    | /usage            | Monthly rollup: used / limit / cost per tenant              |
| POST   | /checkout         | Start a Stripe test-mode upgrade (returns Checkout URL)     |
| POST   | /webhooks/stripe  | Verified, deduplicated Stripe events → plan/status sync     |
| GET    | /health           | Liveness probe                                              |

Design details — schema, idempotency strategy, boundary rule,
layering — in [DESIGN.md](DESIGN.md).

## Architecture

```
Client ─► POST /generate (Idempotency-Key header)
              │
              ├─ 1. retry fast path: key seen before?
              │       └─ yes → return ORIGINAL response (no new event)
              ├─ 2. QuotaService: used + requested <= limit?
              │       ├─ subscription inactive → 402 + message
              │       └─ over limit           → 429 + message
              └─ 3. MeterService: INSERT usage_event(s), one transaction
                      └─ UNIQUE (tenant_id, idempotency_key)
                         = double-count impossible at the DB level

GET /usage ◄── CostService: rollup(usage_events) → { used, limit, cost }
               integer micro-cents, pinned rates, rounded once

POST /checkout ─► Stripe Checkout (test mode, client_reference_id = tenant)
Stripe ─signed webhook─► POST /webhooks/stripe
              ├─ verify signature (forged → 400, nothing changes)
              ├─ dedup: evt_ id is PRIMARY KEY (replay → 200, ignored)
              └─ update tenant plan/status (same transaction as dedup)

Layers: HTTP (routes) → services (meter, quota, cost, stripe_sync) → Postgres.
Routes never contain business logic; the DB enforces what must never
break (idempotency, webhook dedup) via constraints.
```

## Limitations (honest notes)

- No authentication — tenant IDs are trusted identifiers, not
  authenticated principals; anyone who knows a tenant_id can act as
  that tenant. In production, /generate would require an API key or
  JWT bound to the tenant (I built exactly that JWT flow in my A4
  assignment). Out of scope here by the brief's § 6/§ 7 boundaries.

- One paid plan, one Stripe price; plan limits are seed data, not an
  admin API.
- No invoicing, proration, or overage billing — by design (see the
  non-goal in DESIGN.md); over-quota requests are rejected, never billed.
- The monthly usage window is the calendar month in UTC
  (`date_trunc('month', now())`), not a per-tenant billing anchor.
- Local webhook delivery depends on the Stripe CLI listener being up; a
  payment completed while it is down leaves the DB behind Stripe until
  the event is redelivered (a nightly reconciliation job is the natural
  stretch fix — this failure mode was observed live during the build,
  see BUILDLOG).
- Tests run against the dev database (they create their own tenants and
  clean data isn't required), not an isolated test DB.
- Concurrent near-limit requests with different idempotency keys can
  marginally overshoot a quota (check and insert are not one atomic
  step across requests); acceptable at this scope, documented here.
