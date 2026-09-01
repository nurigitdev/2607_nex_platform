# Slice 0468: AE artifact retention purge API guardrail

## Scope

Expose the guarded AE artifact retention purge capability through an
authenticated service API route.

## Changes

- Added `POST /api/v1/artifact-retention/purge`.
- Kept dry-run as the default API behavior.
- Required JSON boolean values for purge control flags.
- Returned `ae_artifact_retention_execution.v1` evidence for dry-run,
  blocked execute, and successful guarded execute.
- Preserved the three-flag execute guard:
  `delete_enabled`, `storage_mutation_enabled`, and
  `database_row_delete_enabled`.
- Added route regression coverage for authentication, missing scope, invalid
  boolean flags, unsafe dry-run delete flags, blocked execute, successful
  guarded execute, and metadata-only response safety.

## Decisions

- The purge route is control-plane only; it does not expose artifact payloads,
  storage refs, filesystem paths, provider secrets, or database URLs.
- String booleans such as `"false"` are rejected instead of silently coerced.
- A dry-run request with any delete flag enabled is rejected by the retention
  execution contract validator.
- PostgreSQL proof remains deferred to the next protected smoke slice.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
