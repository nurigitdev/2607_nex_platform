# Slice 0443: AE Artifact Collection API Wiring

## Scope

Expose the Slice 0442 artifact collection read-model through an authenticated AE
API route.

## Changes

- Added `GET /api/v1/artifacts` to `nex_ae_api.artifacts`.
- Wired query parameters for `tenant_id`, `workspace_id`, `owner_user_id`,
  optional `status`, and bounded `limit`.
- Reused the existing AE artifact authorization and problem response boundary.
- Added route regression coverage for owner-scope filtering, status filtering,
  invalid query handling, unauthorized access, and SQLite-backed default store
  readback.
- Added OpenAPI coverage for the collection endpoint.

## Decisions

- The route requires explicit tenant/workspace/owner scope until browser session
  claims are used directly for artifact library queries.
- Status values are normalized to uppercase and validated against the artifact
  status contract.
- Responses reuse the metadata-only collection read-model from Slice 0442 and
  still exclude rendered payloads, base64 downloads, storage refs, local storage
  roots, database URLs, and provider secrets.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
