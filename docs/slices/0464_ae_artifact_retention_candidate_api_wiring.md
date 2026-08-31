# Slice 0464: AE artifact retention candidate API wiring

Expose the artifact retention candidate read-model through an authenticated AE
API route.

## Scope

- Added `GET /api/v1/artifact-retention/candidates`.
- Reused AE service-claim authorization and existing owner-scope validation.
- Wired query parameters for `tenant_id`, `workspace_id`, `owner_user_id`,
  `retention_days`, `as_of`, and `limit`.
- Added route regression coverage for success, unauthorized calls, missing
  scope, invalid retention days, invalid timestamps, and private-material
  exclusion.

## Decisions

- The route is read-only and dry-run only.
- The route intentionally uses `/api/v1/artifact-retention/candidates` instead
  of nesting under `/api/v1/artifacts/{artifact_id}` so it cannot collide with
  artifact detail lookups.
- API responses still do not include rendered payloads, storage refs, database
  URLs, local paths, or source content.

## Evidence

```text
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
