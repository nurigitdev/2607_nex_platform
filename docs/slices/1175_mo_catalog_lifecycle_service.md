# Slice 1175: MO catalog lifecycle service

## Goal

Add revision-guarded catalog registration and state transitions without changing
any active provider alias.

## Result

- Added deterministic empty-store bootstrap and DRAFT-only catalog registration.
- Added guarded `DRAFT -> ACTIVE`, `DRAFT -> RETIRED`, and
  `ACTIVE -> RETIRED` transitions with terminal retirement.
- Required expected revisions in both service and atomic repository update paths.
- Rejected retirement while an active alias still references the catalog entry.
- Mapped not-found, conflict, filter, and persistence failures to stable service
  status/error contracts.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_catalog_lifecycle_service.py
./.venv/bin/python \
  scripts/smoke/run_mo_catalog_lifecycle_service.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```
