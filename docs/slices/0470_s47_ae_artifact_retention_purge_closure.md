# Slice 0470: S47 AE artifact retention purge closure

## Scope

Close the S47 AE artifact retention and purge track with an automated closure
checkpoint.

## Changes

- Added `scripts/smoke/run_s47_ae_artifact_retention_purge_closure.py`.
- Added `tests/test_s47_ae_artifact_retention_purge_closure.py`.
- Registered the closure checker in the default quality gate.
- Checked S47 file presence, token presence, contiguous slice docs, and the
  retention experience matrix from policy contract through guarded PostgreSQL
  purge evidence.

## Closure Matrix

- Retention/purge boundary audit.
- Retention policy contract/schema.
- Retention candidate read-model.
- Retention candidate API wiring.
- Retention candidate PostgreSQL dry-run smoke.
- Retention execution contract/schema.
- Retention store purge capability.
- Retention purge API guardrail.
- Retention purge PostgreSQL smoke.
- S47 closure checkpoint.

## Decisions

- Dry-run remains the default purge behavior.
- Physical delete remains guarded by all three flags:
  `delete_enabled`, `storage_mutation_enabled`, and
  `database_row_delete_enabled`.
- Handoff lineage is retained after artifact purge.
- PostgreSQL smoke is skipped by default and must be explicitly enabled against
  `NEX_AE_TEST_DATABASE_URL`.
- S47 includes actual guarded physical deletion only inside protected test DB
  smoke evidence, not in the default regression path.

## Evidence

```bash
./.venv/bin/pytest tests/test_s47_ae_artifact_retention_purge_closure.py -q --cov=run_s47_ae_artifact_retention_purge_closure --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_s47_ae_artifact_retention_purge_closure.py --summary
```
