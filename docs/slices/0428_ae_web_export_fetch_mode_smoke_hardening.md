# Slice 0428: AE Web Export Fetch-Mode Smoke Hardening

## Scope

Extend the deterministic AE Web fetch-mode smoke so S43 export submit and binary
download behavior are exercised through the browser adapter boundary.

## Changes

- `apps/nex-ae-web/scripts/runArtifactFetchModeSmoke.mjs` now drives the
  artifact fetch client through:
  - artifact detail, versions, file metadata, preview, and text download;
  - export render-job submit with same-origin `POST`;
  - exported PDF file metadata readback; and
  - exported PDF base64 download.
- The smoke records request observations with safe body shape metadata only.
- Evidence now checks `Idempotency-Key`, `target_formats`, same-origin
  credentials, PDF binary download metadata, and panel redaction.
- Raw text download content and raw base64 bytes are rejected from evidence.

## Decisions

- This remains a deterministic fake-fetch smoke. It proves AE Web adapter shape
  without live network or PostgreSQL access.
- Protected PostgreSQL evidence for persisted export files stays in Slice 0426.
- A later browser-save adapter can build on the normalized `contentBase64`
  client surface, while smoke evidence continues to use panel summaries only.

## Evidence

```bash
npm --prefix apps/nex-ae-web test
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
