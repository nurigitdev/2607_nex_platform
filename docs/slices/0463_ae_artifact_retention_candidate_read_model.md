# Slice 0463: AE artifact retention candidate read-model

Add a metadata-only read-model for artifact retention candidates before exposing
an HTTP route.

## Scope

- Added in-memory and SQLAlchemy `list_retention_candidates(...)` store methods.
- Added candidate filter helpers for tenant/workspace/owner scope, retention
  days, `as_of`, cutoff time, dry-run, and bounded limit.
- Added candidate collection/item builders that omit rendered payloads,
  storage refs, database URLs, and local paths.
- Added SQLite regression coverage for the SQLAlchemy store path.

## Decisions

- The first candidate rule is `artifact_status = DELETED` and
  `updated_at <= as_of - retention_days`.
- `updated_at` is the provisional logical purge timestamp until a later
  execution-history table or dedicated deletion timestamp is justified.
- Candidate results are ordered oldest-first so future batch execution can
  process the longest-retained logical purges before newer ones.
- This Slice still performs dry-run candidate discovery only.

## Evidence

```text
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
