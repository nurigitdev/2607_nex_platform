# Slice 1155: MO durable provider telemetry store adapter

## Goal

Bridge the existing provider telemetry store protocol to the durable repository
without changing its authenticated wire representation.

## Result

- `DurableProviderTelemetryStore` translates success, failure, and retry calls
  into validated atomic mutations.
- Snapshot reads merge durable counters and diagnostics with the current safe
  runtime configuration, preserving all 26 existing telemetry item fields.
- Historical rows that do not match an active runtime identity remain durable
  but are not projected as an active provider route.
- Failure details, provider credentials, endpoints, and payloads never enter a
  mutation or response projection.
- Unknown capability filters remain backward compatible and return an empty
  snapshot without querying persistence.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_store.py \
  tests/test_mo_provider_telemetry_store_smoke.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_store.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_telemetry_store.py \
  --test tests/test_mo_provider_telemetry_store_smoke.py \
  --coverage-target services/nex-mo/nex_mo/provider_telemetry_store.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_store.py
```

## Quality Evidence

- Focused adapter regression: `8 passed`.
- Slice Gate: `576 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.75%`, branch `99.06%`; changed adapter scope
  `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Adapter smoke preserved all 26 wire fields while merging one request, two
  attempts, and one retry without projecting the configured credential.
