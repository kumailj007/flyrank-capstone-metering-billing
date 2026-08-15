# Build Log

Working method: stage-by-stage with Claude (AI assistant). Claude drafts
the code skeleton for some of stage; I review it, place it, run it, debug what
breaks, and don't move on until I can make every line correct. Design
decisions (schema, plan limits, boundary rule, pricing) made in
discussion; debugging done by me. Honest per-stage notes below,
including where the AI-drafted code was wrong and what fixed it.

## 15 Aug — Stage 0–1 (repo + design doc)
Repo public from first commit; .env in .gitignore before anything else.
DESIGN.md: problem, 5-table schema, 5-endpoint API surface, layer rule
(routes never contain business logic), one explicit non-goal (no
invoicing/proration/overage). Key design choice: idempotency and webhook
dedup enforced by DB constraints, not application checks.

## 15 Aug — Stage 2 (scaffold)
FastAPI + Docker Postgres (pinned postgres:16), migrations run on
startup, idempotent seed. Debugged two real issues myself: the old
task-api stack still held port 8000 (`docker compose -p task-api down`),
and the failed first start left a stale network endpoint — the api
container couldn't resolve host `db` ("Temporary failure in name
resolution") until a clean `compose down` + `up` recreated the network.

## 15 Aug — Stage 3 (idempotent metering)
Core pattern: insert-first and let the DB's UNIQUE
(tenant_id, idempotency_key) constraint catch duplicates — a
SELECT-then-INSERT check would race under concurrent retries. Both
events of a request (api_call + ai_tokens) share one transaction; the
token row's key gets a ':tokens' suffix to coexist under the constraint.
Verified with 4 tests including a 5-way concurrent retry.

## 15 Aug — Stage 4 (quotas)
Boundary rule: allowed if used + requested <= limit; 429 = quota
exhausted on an active plan, 402 = subscription not active. Ordering
matters: the retry fast-path runs BEFORE the quota check, so a retry of
an already-recorded request mirrors its original response instead of
429ing — same request, not new usage. The UNIQUE constraint stays as
the safety net underneath.

## 15 Aug — Stage 5 (cost engine)
Money as integers: micro-cents (1/1,000,000 cent), because per-token
prices are fractions of a cent — plain cents would round every token to
zero. Rounding happens once, at rollup, never per event (a pinned test
proves 3 tokens = 300 micro-cents, not 0). Buckets priced at their own
rates and the COSTS summed, never the token counts; cached input = 25%
of input, reasoning billed at the output rate. Rates pinned in
app/pricing.py with exact-total tests so any change breaks loudly.

## 15 Aug — Stage 6 (Stripe, test mode)
The stage with the most real-world friction:
- Windows Defender false-positived the Stripe CLI exe (even though
  winget verified the official installer hash). Sidestepped the fight:
  ran the CLI via Docker (`stripe/stripe-cli` image) with a named volume
  for config and `host.docker.internal` to reach the API on the host.
- AI-drafted webhook code used `event["data"]["object"].get(...)`;
  stripe-python 15.x's object wrapper raises AttributeError on `.get`.
  Fixed by splitting concerns: verify the signature with
  `stripe.WebhookSignature.verify_header` (the security step), then
  `json.loads` the raw payload ourselves — plain dicts, version-proof.
- Learned the difference between `prod_...` (product) and `price_...`
  (price) IDs the practical way: Checkout wants the price ID; Stripe's
  "No such price" error message was the tell.
- First live checkout DIDN'T sync: the CLI listener wasn't running when
  the payment completed, so the webhook had nowhere to go and my DB
  disagreed with Stripe (plan stayed free). Re-ran with the listener
  open: tenant flipped free → pro live. Exactly the failure mode a
  nightly reconciliation job (stretch goal) exists to catch.

## 15 Aug — Stage 7 (submission pack)
capstone.yaml, this log, EVIDENCE.md completed against every § 6
checkbox, README finalized with architecture diagram and honest
limitations. Clean-clone stranger test run before submission.
