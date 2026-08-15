# Build Log

## 15 Aug — Stage 0
Repo created:
generating the code per stage used skeleton base code via claude ; I place it added my code, run it, debug it.

## Stage 2 (scaffold)
files created by me, reviewed by claude. Debugged two real issues
myself: old task-api stack holding port 8000 (fixed with
`docker compose -p task-api down`), then a stale-network
"failed to resolve host 'db'" crash (fixed with clean `down` + `up`).

## Stage 3 (idempotent metering)
Understood the core pattern: insert-first
and let the DB's UNIQUE constraint catch duplicates — no SELECT-first
race. Verified with 4 tests including a 5-way concurrent retry.

## Stage 4 (quotas)
I generated quota service through Claude Assistance , reviewed. Boundary rule: allowed if
used + requested <= limit; 429 = quota exhausted, 402 = subscription
not active. Retry check runs before quota check so a retry of an
already-recorded request mirrors instead of 429ing.

## Stage 5 (cost engine)
Money as integers: micro-cents (1/1,000,000 cent) because per-token
prices are fractions of a cent — cents would round every token to
zero. Rounding happens once, at rollup, never per event. Buckets
priced at their own rates; costs summed, never token counts.
GET /usage live.

