"""Pinned pricing constants — the single source of truth for money math.

Modeled on FlyRank's chat-pricing.config.ts + its test file: rates live
here and ONLY here, and tests/test_cost.py pins exact expected totals so
any accidental change to these numbers breaks the build.

MONEY IS INTEGERS. Everything below is in MICRO-CENTS (1/1,000,000 of a
cent) because per-token prices are tiny fractions of a cent. We sum in
micro-cents and round to whole cents once, at the final rollup. Floats
never touch money: 0.1 + 0.2 != 0.3 in floats, and in billing that's an
overcharge.

The three real-world token rules this config encodes:
  1. cached input is cheaper than fresh input (25% of input rate here)
  2. reasoning tokens are billed AT THE OUTPUT RATE — hidden thinking,
     but you pay for it as output
  3. token categories cannot simply be added together — each bucket is
     priced at its own rate, and you sum the COSTS, not the tokens
"""

MICRO_CENTS_PER_CENT = 1_000_000

# Per-token rates in micro-cents.
# ($ per 1M tokens -> cents per 1M -> micro-cents per token)
TOKEN_RATES = {
    "input_tokens": 100,          # $1.00 / 1M tokens
    "cached_input_tokens": 25,    # $0.25 / 1M tokens (25% of input)
    "output_tokens": 400,         # $4.00 / 1M tokens
    "reasoning_tokens": 400,      # billed as output (rule 2)
}

# Per-API-call rate in micro-cents. ($0.001 per call = $1 per 1,000 calls)
API_CALL_RATE = 100_000


def micro_cents_to_cents(micro: int) -> int:
    """Round micro-cents to whole cents, half up. Integer math only."""
    return (micro + MICRO_CENTS_PER_CENT // 2) // MICRO_CENTS_PER_CENT
