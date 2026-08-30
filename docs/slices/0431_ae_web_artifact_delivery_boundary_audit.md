# Slice 0431: AE Web Artifact Delivery Boundary Audit

## Scope

Start S44 by freezing the AE Web artifact delivery/download boundary before a
browser file-save adapter is added.

## Changes

- Added `scripts/smoke/run_ae_web_artifact_delivery_boundary_audit.py`.
- Added `tests/test_ae_web_artifact_delivery_boundary_audit.py`.
- Registered the delivery boundary audit in the default quality gate.
- Indexed Slice 0431 in the Slice documentation and AE Web notes.

## Decisions

- `nex-ae-api` remains the artifact system of record and the download
  authorization owner.
- `nex-ae-web` may hold the normalized download surface returned by
  `artifactClient.downloadArtifactFile`.
- Only the future browser save adapter may materialize download bytes into a
  local browser file.
- Preview panels, runtime diagnostics, and smoke evidence remain metadata-only
  and must not include raw text download bodies or base64 payloads.
- Protected PostgreSQL/browser evidence must use `nex_ae_test` only when the
  explicit smoke flag is enabled.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_ae_web_artifact_delivery_boundary_audit.py -q --cov=run_ae_web_artifact_delivery_boundary_audit --cov-branch --cov-report=term-missing
```

Boundary summary:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_artifact_delivery_boundary_audit.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
