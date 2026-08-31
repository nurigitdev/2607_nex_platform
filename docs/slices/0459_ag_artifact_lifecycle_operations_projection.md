# Slice 0459: AG Artifact Lifecycle Operations Projection

## Scope

Add an AG-owned read-only lifecycle operations projection over AE artifacts so
operators can inspect archive, restore, and logical delete availability without
bypassing AE as the lifecycle system of record.

## Changes

- Added `ag_artifact_operation_lifecycle_projection.v1` in
  `services/nex-ag/nex_ag/artifact_operations.py`.
- Added `GET /admin/v1/operations/artifacts/{artifact_id}/lifecycle`.
- Added metadata-only lifecycle action summaries for `ARCHIVE`, `RESTORE`, and
  `MARK_DELETED`, including enabled/blocked state, target status, idempotency,
  and safe AE action route references.
- Added lifecycle source status and issue flags for unsupported artifact
  statuses, missing artifact ids, and in-flight rendering state.
- Extended AG artifact operations regression coverage for projection summary,
  status matrix behavior, redaction, route auth/filter failures, source errors,
  and main app route registration.

## Decisions

- AG remains read-only for artifact lifecycle management.
- AE remains the only service that mutates artifact lifecycle state.
- AG lifecycle projection evidence is metadata-only and excludes rendered
  payloads, raw lifecycle comments, local storage paths, database URLs,
  provider credentials, and service tokens.
- Physical deletion and storage purge stay outside S46 lifecycle operations.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov=nex_ag.main --cov-branch --cov-report=term-missing
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
