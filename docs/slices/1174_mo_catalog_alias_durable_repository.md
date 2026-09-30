# Slice 1174: MO catalog and alias durable repository

## Goal

Persist catalog entries and alias binding history through a restart-safe
SQLAlchemy repository and short, constrained PostgreSQL tables.

## Result

- Added `mo_model_catalog` and `mo_alias_bindings` with capability, lifecycle,
  revision, lineage, foreign-key, and one-active-alias constraints.
- Added transactional empty-store bootstrap, catalog and binding inserts,
  filtered reads, deterministic ordering, readback verification, and cleanup.
- Mapped conflicts and unavailable persistence to stable repository errors.
- Proved the repository with fast SQLite restart regression while retaining a
  separate protected PostgreSQL proof for Slice 1180.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_catalog_lifecycle_repository.py \
  tests/test_mo_catalog_lifecycle_repository_smoke.py
./.venv/bin/python \
  scripts/smoke/run_mo_catalog_lifecycle_repository.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```
