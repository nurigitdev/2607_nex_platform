# Slice 0497: AG artifact retention scheduled dispatch control guardrail

Add an AG-protected dispatch guardrail for AE artifact retention scheduled jobs
without letting AG enqueue jobs or write into AE persistence directly.

## Scope

- Added
  `/admin/v1/operations/artifact-retention/scheduled-jobs/dispatch`.
- Added the `ag_artifact_operation_retention_scheduled_dispatch.v1` projection
  contract.
- Extended the AG AE-artifact client with a POST shape for
  `/api/v1/artifact-retention/scheduled-jobs/admission`.
- Required `confirm_dispatch=true` before AG dispatches to AE.
- Rechecked the AE batch plan in AG and blocked dispatch unless the plan is
  READY, DRY_RUN, and has selected candidates.
- Added regression coverage for dispatch projection, redaction, route
  guardrails, source failures, in-memory dispatch synthesis, and HTTP POST
  request/error behavior.

## Decisions

- AG can request AE scheduled job admission, but AE remains the only service
  allowed to enqueue the scheduled retention job.
- Missing trigger type defaults to `operator_dispatch` for this protected AG
  control route.
- The scheduler tick trigger remains available for AE-side scheduler/runtime
  integrations.
- Physical delete automation remains disabled.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
scripts/quality/run_quality_gate.sh
```
