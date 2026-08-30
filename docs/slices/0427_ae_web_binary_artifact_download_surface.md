# Slice 0427: AE Web Binary Artifact Download Surface

## Scope

Harden the AE Web artifact download adapter after S43 introduced DOCX and PDF
binary export files.

## Changes

- `apps/nex-ae-web/src/artifactClient.js` now normalizes text and base64
  download responses into separate browser surface fields.
- Text downloads keep the existing `content` path with `contentEncoding=utf-8`.
- Binary downloads use `contentBase64`, `contentEncoding=base64`,
  `downloadPayloadKind=base64`, decoded `contentLength`, and
  `encodedContentLength`.
- The artifact client summary reports only download metadata and does not carry
  raw text or base64 payload bytes.
- `apps/nex-ae-web/src/artifactPreviewPanel.js` keeps binary downloads as
  metadata-only panel state; downloaded bytes are never rendered into the panel,
  summary, or smoke evidence surface.
- Mock artifact exports now return deterministic base64 payloads for DOCX and
  PDF downloads so browser regression can exercise the binary boundary without a
  live backend.

## Decisions

- AE API remains responsible for persisted rendered payload storage and download
  authorization.
- AE Web may temporarily hold a normalized base64 payload in the client download
  surface so a later browser-save adapter can materialize the file, but panel
  state and summaries must stay metadata-only.
- Unsupported encodings, ambiguous text plus base64 responses, and malformed
  base64 payloads are typed client errors.
- This slice does not add a PostgreSQL smoke because no persisted backend path
  changed. The protected multi-format DB smoke remains the Slice 0426 evidence
  point.

## Evidence

```bash
npm --prefix apps/nex-ae-web test
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
