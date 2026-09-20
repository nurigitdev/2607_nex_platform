# Slice 0903: CX persistence gap re-baseline

## Goal

Replace the stale Slice 0181 persistence checkpoint with a current-state
baseline derived from the implemented CX repository and migrations.

## Findings

- All ten public metadata surfaces have PostgreSQL migrations and repository
  write-through adapters. Their persistence gap is closed.
- Six private payload surfaces remain outside public metadata records. Their
  durability policy is a separate Slice 0904 decision, not a missing public
  database adapter.
- Processing runs are no longer a deferred schema decision. Migration,
  write-through, read model, service API, AG projection, and smoke evidence are
  already present.
- Only optional zero-item lexical and embedding index header tables remain
  deferred. They are optimizations, not MVP blockers.

## Decision

`cx_persistence_gap_audit.v2` reports `REBASELINED` with three explicit classes:

- durable public metadata: `CLOSED`
- private payload durability: `DECISION_REQUIRED`
- optional zero-item index headers: `DEFERRED_OPTIMIZATION`

This slice adds no table or migration and changes no runtime write behavior.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_cx_persistence_gap_rebaseline.py --summary
./.venv/bin/pytest -q \
  tests/test_nex_cx_persistence_audit.py \
  tests/test_cx_persistence_gap_rebaseline.py \
  --cov=nex_cx.persistence_audit \
  --cov=run_cx_persistence_gap_rebaseline \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
rebaseline: PASS metadata_closed=10 metadata_gaps=0 private_boundaries=6
focused tests: 8 passed; target statement/branch coverage: 100%
aggregate regression: 6290 passed, 1 known warning
statement=75754/76635=98.85039472825733%
branch=17660/18310=96.45002730748224%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
