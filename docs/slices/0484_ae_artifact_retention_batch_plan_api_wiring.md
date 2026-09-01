# Slice 0484: AE artifact retention batch plan API wiring

Expose the scheduled retention batch plan as an authenticated AE API read-model
before scheduler or worker execution is introduced.

## Scope

- Added `GET /api/v1/artifact-retention/batch-plan`.
- Reused the Slice 0483 store/runtime read-model rather than adding new
  persistence.
- Accepted tenant, workspace, owner, retention days, scan limit, max delete
  count, `as_of`, `checked_at`, and `Idempotency-Key` inputs.
- Added route regression coverage for:
  - authenticated READY plan response
  - NOOP plan response
  - missing/invalid scope and delete limit errors
  - unauthorized access
  - metadata-only redaction and no artifact mutation

## Decisions

- The route is GET-only and returns a plan, not an execution command.
- `requested_by` is currently stamped as `nex-ag` because AG is the intended
  operator projection and dispatch caller for this S49 surface.
- The route keeps `scheduler_status=DISABLED` and all mutation flags false.
- Persisted history remains owned by the guarded purge route; this endpoint is
  an inspection/readiness surface.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
scripts/quality/run_quality_gate.sh
```
