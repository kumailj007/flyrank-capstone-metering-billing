# FlyRank Capstone — Usage Metering & Billing Engine

A backend service that meters usage, enforces subscription quotas,
calculates costs (including AI token pricing rules), and syncs plans
via Stripe (test mode) with signature-verified, idempotent webhooks.

**Stack:** Python · FastAPI · PostgreSQL (Docker) · Stripe test mode

## Status

🚧 In progress — Stages 0–5 done: idempotent metering, quota
enforcement (429/402), pinned cost engine, GET /usage. 14 tests green.
Next: Stripe test-mode integration. Build log in BUILDLOG.md.

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

14 tests: idempotency (incl. concurrent retries), quota boundaries
(at / just under / over the limit, 429 and 402), and pinned pricing
(cached-input and reasoning-token rules, exact expected totals).

## API

| Method | Path              | What it does                                              |
| ------ | ----------------- | --------------------------------------------------------- |
| POST   | /generate         | Dummy billable endpoint — idempotent metering + quota check |
| GET    | /usage            | Monthly rollup: used / limit / cost per tenant             |
| POST   | /checkout         | Start a Stripe test-mode upgrade *(Stage 6)*               |
| POST   | /webhooks/stripe  | Verified, deduplicated Stripe events *(Stage 6)*           |
| GET    | /health           | Liveness probe                                             |

Design details — schema, idempotency strategy, boundary rule,
layering — in [DESIGN.md](DESIGN.md).

## Architecture

_Diagram coming in Stage 7._

## Limitations

_Honest notes coming in Stage 7._