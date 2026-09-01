# Slice 0488: AG artifact retention batch operations projection

Add the AG read-only operations surface for AE scheduled artifact retention batch
plans.

## Changes

- Added `ag_artifact_operation_retention_batch_projection.v1`.
- Added
  `GET /admin/v1/operations/artifact-retention/batch-plan` to read AE's
  metadata-only batch plan through the artifact operations client boundary.
- Added in-memory and HTTP client support for AE
  `GET /api/v1/artifact-retention/batch-plan`.
- Added projection summary fields for plan status, scheduler status, candidate
  counts, selected counts, estimated delete counts, and dispatch availability.
- Preserved the AG boundary: AG reads and projects the AE plan, but does not
  mutate AE artifact rows, rendered storage, retention history, or scheduler
  state.

## Guardrails

- Projection output omits local storage paths, rendered artifact content,
  database URLs, raw execution payloads, and system prompts.
- `tenant_id`, `workspace_id`, and `owner_user_id` are required on the AG route.
- `retention_days`, `scan_limit`, and `max_delete_count` are validated before
  the AE client is called.
- Operator guidance keeps physical delete confirmation explicit and marks direct
  AG database writes as disallowed.

## Verification

- `./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing`
