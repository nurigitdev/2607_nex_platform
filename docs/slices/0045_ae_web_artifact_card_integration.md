# Slice 0045 AE Web Artifact Card Integration

Status: Implemented.

Backlog candidate: `S5-005` AE web artifact card integration.

Requirement coverage: `AEWEB-FR-003`, `AEWEB-FR-004`, `AEAPI-FR-004`,
`AEAPI-FR-005`, `AEAPI-FR-006`, `TRACE-AE-001`, `TRACE-GEN-001`.

## Scope

Slice 0045 updates the static AE web workspace to consume the new artifact
record and chat artifact link shapes:

- Mock `artifactRef` state aligned with `artifact_refs` from
  `ae_chat_interaction.v1`.
- Assistant message artifact link row with status, version, source, preview, and
  download actions.
- Artifact side panel metadata for current version, preview route, and download
  route.
- Composer mock flow that updates generated artifact ref metadata per selected
  format.
- Static tests for Slice 0045 anchors, artifact link JS state, path redaction,
  responsive CSS guards, and package version.

The shell remains static and mock-first. Backend calls are still limited to
readiness checks until a browser mediation path for service-authenticated AE API
calls is added.

## Files

- `apps/nex-ae-web/index.html`
- `apps/nex-ae-web/src/main.js`
- `apps/nex-ae-web/src/styles.css`
- `apps/nex-ae-web/package.json`
- `apps/nex-ae-web/README.md`
- `tests/test_nex_ae_web_static.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
npm --prefix apps/nex-ae-web run dev
```

Regression tests cover workspace DOM anchors, artifact ref mock state,
preview/download action metadata, no raw prompt/provider/path leakage,
responsive layout guardrails, artifact link styles, and package metadata.
