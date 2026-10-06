# Slice 1378: AG Durable Trace Audit and Operations API

## Goal

Switch the protected AG trace route from compatibility database projections to
the service-API aggregator and persist every successful read as redacted,
restart-safe AG audit evidence.

## Implementation

- Moved `/admin/v1/operations/traces/{trace_id}` out of the legacy unified
  operations registry and into the dedicated service-API trace module.
- Wired OA, AE, CX, and MO HTTP aggregation into the runtime route.
- Reused AG's existing `service_operational_events` table and trace index; no
  new table or migration was added.
- Persisted one `ag.cross_service_trace.read.succeeded` event containing only
  status counts, stage count, diagnostic count/codes, and the queried trace id.
- Fail closed with `503` when durable audit emission is unavailable, preventing
  unaudited operations reads.
- Appended the persisted AG audit as an `OPERATIONS` stage and `nex-ag` source,
  giving the canonical response five explicit sources.
- Updated OpenAPI to return `AgCrossServiceTraceE2E` and removed obsolete
  compatibility database filter parameters.

Actual PostgreSQL persistence remains assigned to Slice 1380. This Slice uses
the same runtime store interface with deterministic in-memory evidence and does
not call remote model providers.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-ag \
  --test tests/test_nex_ag_cross_service_trace.py \
  --test tests/test_ag_cross_service_trace_operations_contract.py \
  --coverage-target services/nex-ag/nex_ag/cross_service_trace.py \
  --coverage-target scripts/smoke/run_ag_cross_service_trace_operations_contract.py \
  --smoke scripts/smoke/run_ag_cross_service_trace_operations_contract.py
```

Observed evidence:

- regression: `2470 passed`
- statement coverage: `98.87%`
- branch coverage: `96.48%`
- `cross_service_trace.py`: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` examples, `196` negative
  examples, `7` OpenAPI documents
- smoke: `checks=12/12`, `sources=5`, `stages=5`, `audit=1`, `next=1379`
