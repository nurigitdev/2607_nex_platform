# Slice 0412: AE Web Artifact Client Adapter Foundation

Status: Implemented.

Add the browser-side artifact client boundary that will feed the S42 artifact
card and preview/download surfaces.

## Scope

Slice 0412 adds:

- `src/artifactClient.js` with mock and fetch adapters for:
  - `GET /api/v1/artifacts/{artifact_id}`
  - `GET /api/v1/artifacts/{artifact_id}/versions`
  - `GET /api/v1/artifact-files/{artifact_file_id}`
  - `GET /api/v1/artifact-files/{artifact_file_id}/preview`
  - `GET /api/v1/artifact-files/{artifact_file_id}/download`
- Client registry composition for `artifactClient`.
- Safe browser surfaces that omit AE storage refs, storage paths, service
  credentials, provider endpoints, database endpoints, raw prompts, and source
  text.
- Summary helpers that do not include downloaded artifact content.

The shell remains mock-first. This slice does not add new UI controls yet.

## Evidence

```bash
npm --prefix apps/nex-ae-web test -- artifactClient.test.mjs clientRegistry.test.mjs
```

```bash
./.venv/bin/pytest tests/test_ae_web_artifact_surface_boundary_audit.py -q --cov=run_ae_web_artifact_surface_boundary_audit --cov-branch --cov-report=term-missing
```
