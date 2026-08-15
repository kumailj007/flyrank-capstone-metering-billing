## Cost calculation: pinned pricing tests, cached-input & reasoning rules

`docker compose exec api pytest tests/test_cost.py -v`

```
test_pinned_total_one_million_of_each_bucket_is_exactly_925_cents PASSED
test_cached_input_is_cheaper_than_fresh_input PASSED
test_reasoning_tokens_billed_at_output_rate PASSED
test_categories_cannot_simply_be_added PASSED
test_rounding_happens_once_at_rollup_not_per_event PASSED
test_usage_endpoint_reports_pinned_cost PASSED
==== 14 passed in 3.68s ==== (full suite)
```

1M of each bucket = exactly 925 cents ($1.00 input + $0.25 cached +
$4.00 output + $4.00 reasoning-as-output). Rates pinned in
app/pricing.py; all math in integer micro-cents, rounded to cents
once at rollup.