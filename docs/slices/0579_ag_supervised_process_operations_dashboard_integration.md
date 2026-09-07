# Slice 0579: AG supervised process operations dashboard integration

## Scope

Add AE-owned supervised scheduler daemon process snapshot evidence to the AG
artifact retention automation operations dashboard.

## Implementation

- Extended `GET /admin/v1/operations/artifact-retention/automation` with a
  `scheduler_daemon_processes` read-only block.
- The automation summary now includes supervised process record counts,
  running/failed/stale/blocked counts, adapter-required counts, status counts,
  process attention state, and latest process observation time.
- AG fetches the process snapshot collection through the AE artifact operations
  client using the scheduler id from AE's daemon config.
- Process snapshot source failures degrade only the process rollup. Existing
  batch-plan, scheduled-job, history, and daemon-config evidence remains
  available when those sources succeed.
- The AG automation smoke now includes one `RUNNING` and one `STALE` supervised
  process snapshot so the operator dashboard evidence covers both healthy and
  attention-required process states.

## Guardrails

- AE remains the system of record for process snapshot persistence.
- AG does not write AE tables, enqueue AE jobs, or start/stop subprocesses.
- The dashboard exposes only projected metadata and omits raw
  `supervised_process_snapshot` payloads, database URLs, storage paths, and raw
  daemon runtime payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py tests/test_nex_ag_artifact_operations.py tests/test_ag_artifact_retention_automation_operations_smoke.py
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py tests/test_ag_artifact_retention_automation_operations_smoke.py -q --cov=nex_ag.artifact_operations --cov=run_ag_artifact_retention_automation_operations_smoke --cov-branch --cov-report=term-missing
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/python scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py --summary
```

Targeted regression: 81 passed. Script coverage: 100%. AG artifact operations
module coverage: 97%.

Smoke summary:

```text
ag_artifact_retention_automation_operations_smoke=pass route_status=200 safety=FAILED_ATTENTION scheduled_jobs=2 history=2 daemon_manual=True daemon_attention=READY process_running=1 process_attention=True approval_blocked=1
```

## Next

- Slice 0580 should close S58 by checking that supervised process activation,
  persistence, AG read model, and dashboard integration evidence are all wired.
