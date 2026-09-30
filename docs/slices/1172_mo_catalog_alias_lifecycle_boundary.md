# Slice 1172: MO catalog and alias lifecycle boundary audit

## Goal

Freeze the ownership, persistence, privacy, concurrency, activation, rollback,
and compatibility boundaries for S118 before catalog lifecycle implementation.

## Result

- Confirmed that the current model catalog and alias routes are static process
  configuration without mutation history or restart-safe lifecycle state.
- Selected `mo_model_catalog` and `mo_alias_bindings` as the two short durable
  table names, with SQLite regression and PostgreSQL production semantics.
- Kept provider endpoints, API keys, authorization tokens, SSH targets, model
  paths, and database URLs outside the database and public projections.
- Required expected-revision mutation guards, one active binding per logical
  alias and capability, atomic activation, and append-only rollback bindings.
- Retained static routes only as an empty-store bootstrap and compatibility
  fallback while assigning durable runtime resolution to Slice 1178.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_catalog_lifecycle_boundary.py
./.venv/bin/python \
  scripts/smoke/run_mo_catalog_lifecycle_boundary.py --summary
scripts/quality/run_slice_gate.sh
```

## Decision

S118 persists public model identity and logical alias binding metadata. Runtime
connection configuration remains environment-owned so catalog operations can
never expose or overwrite credentials and private infrastructure addresses.
