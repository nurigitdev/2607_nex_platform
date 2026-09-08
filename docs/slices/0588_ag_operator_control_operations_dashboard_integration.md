# Slice 0588: AG operator-control operations dashboard integration

## Scope

Fold the AE-owned scheduler daemon operator-control policy and safe status-probe
preview into the AG artifact-retention automation dashboard.

## Implementation

- Extended the AG artifact-retention automation projection with an
  `operator_control` section containing redacted policy, facade, summary, and
  preview-only metadata.
- Added operator-control fields to the automation summary:
  `operator_control_policy_loaded`, `operator_control_facade_loaded`,
  `operator_control_action`, `operator_control_facade_status`,
  `operator_control_command_preview_count`, and guardrail flags.
- Added operator-control source health to automation `source_status`, degrading
  the dashboard when policy/preview lookups fail without hiding the remaining
  batch/job/history/process state.
- Updated the automation route to call AE's operator-control policy endpoint and
  a safe `status_probe` preview. Current process metadata is projected from AE
  supervised-process snapshots before it is passed to the preview.
- Updated the AG automation smoke runner to require operator-control dashboard
  rollup and preview guardrails.

## Guardrails

- The dashboard status-probe remains preview-only.
- AG still cannot dispatch supervisor commands, write AE persistence, enqueue AE
  jobs, or signal AE subprocesses directly.
- Operator-control failures degrade the dashboard evidence instead of becoming
  direct AG process-control attempts.
- Projection continues to redact idempotency keys, database URLs, storage paths,
  and raw private payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py tests/test_nex_ag_artifact_operations.py tests/test_ag_artifact_retention_automation_operations_smoke.py tests/test_ae_ag_artifact_retention_scheduler_postgres_smoke.py
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py tests/test_ag_artifact_retention_automation_operations_smoke.py tests/test_ae_ag_artifact_retention_scheduler_postgres_smoke.py -q
./scripts/quality/run_quality_gate.sh
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py --summary
```

Results:

- Full quality gate: `3975 passed`, statement coverage `98.59%`, branch
  coverage `95.81%`.
- Protected PostgreSQL smoke:
  `ae_ag_artifact_retention_scheduler_postgres_smoke=pass ... live_db=true`.

## Next

- Slice 0589 should prove AG-to-AE operator-control dashboard and preview
  evidence against the real test DBs under protected smoke flags.
