# Slice 1147: MO provider retry telemetry

## Goal

Make retry behavior visible without changing the existing logical request
counters or prematurely adding durable telemetry storage.

## Result

- Provider telemetry now distinguishes logical request count from total remote
  attempt count and retry count.
- Safe last-retry metadata includes timestamp, bounded delay milliseconds, and
  failure kind only.
- A retry followed by success records one request, two attempts, one retry, one
  success, and zero logical failures.
- The authenticated provider telemetry schema and canonical fixture include the
  new counters and nullable last-retry fields.
- State remains process-local. Restart-safe aggregate persistence is still S116
  and no database table is added by S115.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_retry_telemetry.py
./.venv/bin/python scripts/smoke/run_mo_provider_retry_telemetry.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_retry_telemetry.py \
  --coverage-target services/nex-mo/nex_mo/provider_telemetry.py \
  --smoke scripts/smoke/run_mo_provider_retry_telemetry.py
```

## Quality Evidence

- Focused MO remote-provider and telemetry regression: `140 passed`.
- Slice Gate: `500 passed`, `1` protected PostgreSQL smoke skip.
- Coverage: statement `99.70%`, branch `98.88%`; changed telemetry scope
  reached statement `100.00%` and branch `100.00%`.
- Contract validation remained `119/177/145/7`.
- Retry telemetry smoke recorded one logical request, two provider attempts,
  and one retry (`6/6` checks).
