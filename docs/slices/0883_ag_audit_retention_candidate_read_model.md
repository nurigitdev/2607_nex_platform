# Slice 0883: AG audit retention candidate read model

## Goal

Select bounded retention candidates from the two AG source tables without
modifying rows or exposing archived payload content.

## Implementation

- Added a common candidate-page builder with stable oldest-first ordering by
  source timestamp, source kind, and source identity.
- Added in-memory and SQLAlchemy candidate stores.
- Applied each source's policy cutoff and the policy batch size, with a hard
  maximum of 500 candidates.
- Returned source identity, timestamp, retention cutoff, and canonical SHA-256
  only. Event messages/details and evidence manifests are never projected.
- Marked every unarchived candidate as `purge_eligible=false`.
- Normalized malformed timestamps and missing identities as invalid records;
  database failures produce a safe 503-class domain error without SQL details.
- Added SQLite regression coverage for both source query shapes.

This Slice is read-only. It does not add a table, seal an archive receipt, or
delete a source row.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_audit_retention.py \
  --cov=nex_ag.audit_retention --cov-branch --cov-report=term-missing
```

Observed verification:

```text
policy and candidate tests: 38 passed
audit_retention module statement/branch: 100%
aggregate regression: 6055 passed, 1 known warning
statement=73903/74784=98.821940522037%
branch=17284/17934=96.375599420096%
```
