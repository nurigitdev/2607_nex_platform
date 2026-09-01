# Slice 0481: AE artifact retention scheduled operations boundary audit

Start S49 by freezing the scheduled artifact retention operations boundary
before adding schedule schemas, batch plans, workers, or AG dispatch controls.

## Scope

- Added `scripts/smoke/run_ae_artifact_retention_scheduled_operations_boundary_audit.py`.
- Added regression coverage for pass/fail evidence, redaction, CLI output, docs,
  and quality-gate wiring.
- Confirmed S49 starts from the closed S47/S48 retention purge and history
  baseline.

## Decisions

- `nex-ae-api` remains the artifact retention system of record.
- `nex-ag` owns operator projection and future dispatch UX, but must not write
  directly into the AE database.
- Scheduled operations default to `DRY_RUN` and reuse the existing 30-day
  logical-purge retention policy with 15-day and 30-day presets.
- The first scheduled window remains `02:00-05:00` in `Asia/Seoul`.
- Execute-mode deletion still requires `delete_enabled`,
  `storage_mutation_enabled`, and `database_row_delete_enabled`.
- Slice 0481 does not add a scheduler daemon, worker execution, or new mutation
  endpoint.

## Planned Gaps

- Slice 0482: schedule contract/schema.
- Slice 0483: metadata-only batch plan read-model.
- Slice 0484: authenticated AE batch plan API.
- Slice 0485: batch plan PostgreSQL smoke evidence.
- Slice 0486: scheduled execution command foundation.
- Slice 0487: mock worker pipeline.
- Slice 0488: AG batch operations projection.
- Slice 0489: scheduled execution PostgreSQL smoke.
- Slice 0490: S49 closure checkpoint.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduled_operations_boundary_audit.py -q --cov=run_ae_artifact_retention_scheduled_operations_boundary_audit --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduled_operations_boundary_audit.py --summary
```
