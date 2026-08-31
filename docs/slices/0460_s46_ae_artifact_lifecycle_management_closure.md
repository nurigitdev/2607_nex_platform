# Slice 0460: S46 AE Artifact Lifecycle Management Closure

## Scope

Close the S46 artifact lifecycle management track with an automated closure
checker.

## Changes

- Added `scripts/smoke/run_s46_ae_artifact_lifecycle_management_closure.py`.
- Added `tests/test_s46_ae_artifact_lifecycle_management_closure.py`.
- Registered the closure checker in the default quality gate.
- Indexed Slice 0460 in the Slice documentation and service notes.

## Closure Matrix

- Artifact lifecycle boundary audit.
- AE lifecycle command/result contract.
- AE lifecycle repository/API route.
- AE lifecycle PostgreSQL smoke evidence.
- AE Web lifecycle client adapter.
- AE Web lifecycle action state.
- AE Web lifecycle UX wiring.
- AE Web lifecycle Playwright/PostgreSQL smoke evidence.
- AG lifecycle operations projection.
- S46 closure checkpoint.

## Decisions

- AE remains the artifact lifecycle system of record.
- AE Web owns the user-facing artifact lifecycle action surface.
- AG owns read-only lifecycle projections and must not mutate AE state.
- S46 lifecycle actions remain reversible metadata actions: `ARCHIVE`,
  `RESTORE`, and logical `MARK_DELETED`.
- Physical file deletion, storage purge, object-storage mutation, and retention
  execution remain outside S46.
- Lifecycle evidence remains metadata-only and excludes rendered content, raw
  lifecycle comments, raw prompts, raw generation output, local storage paths,
  database URLs, service tokens, and provider credentials.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_s46_ae_artifact_lifecycle_management_closure.py -q --cov=run_s46_ae_artifact_lifecycle_management_closure --cov-branch --cov-report=term-missing
```

Closure summary:

```bash
./.venv/bin/python scripts/smoke/run_s46_ae_artifact_lifecycle_management_closure.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
