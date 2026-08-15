# Build Log

Working method: Claude drafts
the skeleton code for each stage; I review it, place it, run it, debug what
breaks, and don't move on until I can understand and make sure every line is perfect. Design
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
container couldn't resolve host `db` until a clean `down` + `up`
recreated the network.

## 15 Aug — Stage 3 (idempotent metering)
Core pattern: insert-first and let the DB's UNIQUE
(tenant_id, idempotency_key) constraint catch duplicates — a
SELECT-then-INSERT check would race under concurrent retries. Both
events of a request share one transaction; the token row's key gets a
':tokens' suffix to coexist under the constraint. Verified with 4 tests
including a 5-way concurrent retry.

## 15 Aug — Stage 4 (quotas)
Boundary rule: allowed if used + requested <= limit; 429 = quota
exhausted on an active plan, 402 = subscription not active. Ordering
matters: the retry fast-path runs BEFORE the quota check, so a retry of
an already-recorded request mirrors its original response instead of
429ing.

## 15 Aug — Stage 5 (cost engine)
Money as integers: micro-cents, because per-token prices are fractions
of a cent — plain cents would round every token to zero. Rounding
happens once, at rollup, never per event. Buckets priced at their own
rates and the COSTS summed, never the token counts. Rates pinned in
app/pricing.py with exact-total tests.

## 15 Aug — Stage 6 (Stripe, test mode)
The stage with the most real-world friction:
- Windows Defender false-positived the Stripe CLI exe (despite winget
  verifying the official installer hash). Sidestepped it: ran the CLI
  via Docker (stripe/stripe-cli image), named volume for config,
  host.docker.internal to reach the API on the host.
- AI-drafted webhook code used `.get(...)` on the parsed event;
  stripe-python 15.x's object wrapper raises AttributeError on it.
  Fixed by splitting concerns: verify the signature with
  stripe.WebhookSignature.verify_header, then json.loads the raw
  payload — plain dicts, version-proof.
- Learned prod_ (product) vs price_ (price) IDs the practical way:
  Checkout wants the price ID; "No such price" was the tell.
- First live checkout DIDN'T sync: the CLI listener wasn't running when
  the payment completed, so the webhook had nowhere to go and my DB
  disagreed with Stripe. Re-ran with the listener open: tenant flipped
  free → pro live.

## 15 Aug — Stage 7 (submission pack + the § 12 catch)
capstone.yaml, EVIDENCE.md completed against every § 6 checkbox, README
finalized with diagram and honest limitations (including: no
authentication — out of scope here; the JWT flow lives in my A4
assignment). Re-reading § 12 before submitting caught a real gap:
shared requirement #3 (a background job) was unmet.

## 15 Aug — Stage 7.5 (reconciliation job)
Built jobs/reconcile.py — the nightly DB-vs-Stripe comparison, and the
exact cure for the missed-webhook drift I hit live in Stage 6. Retries
transient Stripe failures with backoff, survives one permanently dead
record, exits non-zero with a FAILURE ALERT on total outage. Two testing
lessons the suite itself taught me:
- The retry test counted stub calls across ALL subscriptions in the DB
  (13 != 3) — scoped the stub to the test's own sub.
- Worse: an unscoped "everything is canceled" stub ran the job against
  the whole database and CANCELED the real demo tenants — my own
  reconciler broke real data on a stubbed lie. Scoped every stub, then
  used the real reconcile job itself (against real Stripe) to repair
  the tenants it had broken. Test isolation is not optional in a suite
  that shares a database.
Suite now 22 tests, all green.