# Slice 1207: OA API, OpenAPI, and contract drift audit

## Goal

Measure NeX-OA runtime/API contract drift before adding another identity route or
wire shape.

## Result

- Runtime composition currently exposes 29 HTTP operations across OA-owned and
  registered shared runtime routes.
- `nex-oa.openapi.yaml` documents 6 operations and misses 23 current runtime
  operations; it has no operation that is absent from runtime.
- The OpenAPI version remains stale at `0.0.0-slice0003`.
- Both OA JSON Schemas have positive fixtures, while the subject-registry
  snapshot lacks a negative fixture.
- Total classified drift is 25 items: 23 missing operations, one missing
  negative fixture, and one stale version.
- S122 must introduce canonical schemas per wire shape, security declarations
  for internal routes, fixture parity, and exact runtime/OpenAPI parity before
  adding new routes.
- No runtime route, schema, table, or migration is changed in this audit.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_oa_contract_api_drift_audit.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_contract_api_drift_audit.py \
  --coverage-target services/nex-oa/nex_oa/contract_api_drift_audit.py \
  --coverage-target scripts/smoke/run_oa_contract_api_drift_audit.py \
  --smoke scripts/smoke/run_oa_contract_api_drift_audit.py
```
