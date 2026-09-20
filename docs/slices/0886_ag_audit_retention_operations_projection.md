# Slice 0886: AG audit retention operations projection

## Goal

Expose S89 policy, candidates, archive receipts, and guarded purge through one
protected NeX-AG operations surface.

## Implementation

- Added `GET /admin/v1/operations/audit-retention` for policy, bounded candidate
  pages, receipt status counts, purge-ready counts, and attention reasons.
- Added `POST /admin/v1/operations/audit-retention/purge` as a thin adapter over
  the Slice 0885 guarded service; it does not duplicate deletion rules.
- Required service scope or an authenticated admin user role.
- Added production runtime wiring that selects SQLAlchemy stores when the AG
  persistence runtime is configured and shared in-memory stores otherwise.
- Excluded raw source payload, archive object references, credentials,
  confirmation values, and receipt/source hashes from the operations response.
- Added route, authorization, projection, purge, and runtime-adapter regression
  coverage.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_audit_retention_operations.py \
  --cov=nex_ag.audit_retention_operations --cov-branch \
  --cov-report=term-missing
```

Observed verification:

```text
operations tests: 11 passed, 1 known warning
operations module statement/branch: 100%
aggregate regression: 6123 passed, 1 known warning
statement=74392/75273=98.829593612584%
branch=17446/18096=96.408045977011%
```
