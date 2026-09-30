# Slice 1151: S115 MO provider resilience and retry closure

## Goal

Close S115 with bounded retry, telemetry, readiness composition, real HTTP,
contract, privacy, and Full Gate evidence before durable MO observability work.

## Result

- Embedding and reranking are bounded to three attempts; generation is bounded
  to two and blocks ambiguous response replay.
- Retry execution remains within one logical provider request with bounded
  jitter and capped `Retry-After` handling.
- Telemetry distinguishes logical requests, provider attempts, and retries;
  readiness remains authoritative for current route availability.
- Deterministic loopback HTTP proves all three real transport paths without
  depending on external DGX availability.
- Canonical schema, explicit OpenAPI fields, authenticated runtime output, and
  zero operation drift remain aligned.
- S115 adds no database table and requires no PostgreSQL smoke. Restart-safe
  telemetry is handed to S116 and GPU/runtime observability remains S117.

## Verification

```bash
./.venv/bin/pytest -q tests/test_s115_mo_provider_resilience_retry_closure.py
./.venv/bin/python \
  scripts/smoke/run_s115_mo_provider_resilience_retry_closure.py --summary
scripts/quality/run_quality_gate.sh
```

## Quality Evidence

- Focused closure regression: `6 passed`.
- Full Gate: `9,190 passed`, `6` protected skips; AE Web Node regression
  passed `293/293`.
- Coverage: statement `98.81%`, branch `97.03%`, above the repository
  thresholds of `95%` and `85%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- S115 closure evidence passed `9/9`, all `5/5` components closed, three
  capabilities completed six loopback HTTP attempts, and contract drift was
  `0`.
- The default Full Gate kept PostgreSQL and external DGX probes explicitly
  opt-in. S115 created no database table and required neither dependency.
