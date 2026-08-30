# Slice 0441: AE Artifact Library Management Boundary Audit

## Scope

Start S45 by freezing the artifact library and operations boundary before
owner-scoped collection read-models and list APIs are added.

## Changes

- Added `scripts/smoke/run_ae_artifact_library_management_boundary_audit.py`.
- Added `tests/test_ae_artifact_library_management_boundary_audit.py`.
- Registered the audit in the default quality gate.
- Indexed Slice 0441 in the Slice documentation, AE API notes, and AE Web notes.

## Decisions

- `nex-ae-api` remains the artifact system of record.
- `nex-ae-web` owns the browser artifact library surface.
- `nex-ag` owns operator projections and should keep reading AE artifact
  metadata through an AE client boundary.
- Artifact collections must be scoped by tenant, workspace, and owner.
- Collection responses are metadata-only: IDs, statuses, titles, formats,
  quality summaries, timestamps, route links, and hashes are allowed.
- Rendered payloads, raw prompts, raw generation output, local storage paths,
  database URLs, provider secrets, and storage roots remain outside collection
  evidence and browser diagnostics.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_ae_artifact_library_management_boundary_audit.py -q --cov=run_ae_artifact_library_management_boundary_audit --cov-branch --cov-report=term-missing
```

Boundary summary:

```bash
./.venv/bin/python scripts/smoke/run_ae_artifact_library_management_boundary_audit.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
