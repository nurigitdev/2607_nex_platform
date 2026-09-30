# Slice 1177: MO authenticated catalog lifecycle API

## Goal

Expose catalog and alias lifecycle reads and mutations through authenticated MO
service APIs with server-derived audit identity and safe problem responses.

## Result

- Added authenticated catalog collection/detail/register/transition routes.
- Added authenticated alias history, activate, and rollback routes.
- Derived `changed_by` from the validated service token subject and excluded it,
  credentials, endpoints, model paths, and database URLs from projections.
- Added a lock-protected in-memory repository for deterministic default runtime
  and SQL repository selection for PostgreSQL runtime.
- Built one catalog lifecycle service in the MO runtime and mapped validation,
  conflict, not-found, and persistence failures to stable problem responses.
- Deferred main-app route registration until Slice 1179 so the seven new
  operations enter runtime, JSON Schema, fixtures, and OpenAPI atomically.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_catalog_lifecycle_api.py
./.venv/bin/python scripts/smoke/run_mo_catalog_lifecycle_api.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```
