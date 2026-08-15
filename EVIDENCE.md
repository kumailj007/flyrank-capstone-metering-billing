# Evidence

One pasted proof per Definition-of-Done checkbox (§ 6 of the brief).

## Metering: exactly one usage event under retries, proven by test

`docker compose exec api pytest tests/test_idempotency.py -v`

```
tests/test_idempotency.py::test_retry_same_key_creates_one_event_and_mirrors_response PASSED
tests/test_idempotency.py::test_concurrent_retries_create_one_event PASSED
tests/test_idempotency.py::test_different_keys_create_separate_events PASSED
tests/test_idempotency.py::test_missing_idempotency_key_rejected PASSED
==== 4 passed in 0.77s ====
```

The concurrent test fires 5 identical requests simultaneously; the DB's
UNIQUE (tenant_id, idempotency_key) constraint guarantees a single event.