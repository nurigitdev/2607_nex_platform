# Slice 0451: AE Artifact Lifecycle Boundary Audit

## Scope

Start S46 by freezing the reversible artifact lifecycle boundary before command
contracts and mutation routes are added.

## Changes

- Added `scripts/smoke/run_ae_artifact_lifecycle_boundary_audit.py`.
- Added `tests/test_ae_artifact_lifecycle_boundary_audit.py`.
- Registered the lifecycle audit in the default quality gate.
- Indexed Slice 0451 in the Slice documentation, AE API notes, AE Web notes,
  and AG notes.

## Decisions

- `nex-ae-api` remains the artifact lifecycle system of record.
- `nex-ae-web` owns the browser artifact lifecycle action surface.
- `nex-ag` owns read-only operator lifecycle projections and issue candidates.
- S46 initially allows only reversible metadata actions:
  `ARCHIVE`, `RESTORE`, and `MARK_DELETED`.
- `MARK_DELETED` is a logical delete that remains reversible/admin-visible.
- Physical file deletion, storage purge, object-storage deletion, and retention
  execution are deferred to a later retention/purge track.
- Lifecycle evidence remains metadata-only and must not include rendered
  payloads, raw prompts, raw generation output, storage roots, local paths,
  database URLs, provider credentials, or service tokens.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_ae_artifact_lifecycle_boundary_audit.py -q --cov=run_ae_artifact_lifecycle_boundary_audit --cov-branch --cov-report=term-missing
```

Boundary summary:

```bash
./.venv/bin/python scripts/smoke/run_ae_artifact_lifecycle_boundary_audit.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
