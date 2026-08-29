# Slice 0414: AE Web Artifact Card Rendering

Status: Implemented.

Render chat artifact refs through the S42 read-model and a dedicated safe HTML
renderer.

## Scope

Slice 0414 adds:

- `src/artifactCard.js` for artifact card rendering and renderer summaries.
- `main.js` wiring from `artifactRefs` to
  `buildArtifactCardCollectionReadModel` and `renderArtifactCard`.
- Stable `data-artifact-*` anchors for preview/download interactions planned in
  Slice 0415.
- CSS for card actions and warning states while preserving existing
  `.artifact-link` compatibility.

## Evidence

```bash
node --test apps/nex-ae-web/test/artifactCard.test.mjs apps/nex-ae-web/test/artifactCardReadModel.test.mjs
```

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```
