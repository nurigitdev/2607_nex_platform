# Slice 0040 AE Web Workspace Shell Integration

Status: Implemented.

Backlog candidate: `S4-010` AE web MVP workspace shell integration.

Requirement coverage: `AEWEB-FR-001`, `AEWEB-FR-002`, `AEWEB-FR-003`,
`AEWEB-FR-004`, `AEAPI-FR-005`, `AG-FR-003`, `TRACE-GEN-001`.

## Scope

Slice 0040 upgrades the static `nex-ae-web` shell into a mock-first workspace
surface:

- Korean-default workspace summary band.
- Service readiness strip and service status list.
- Chat message stream and composer with retrieval and target format controls.
- Document scope list with summary readiness and confidence state.
- Generation progress timeline aligned to `generation_progress_event.v1`.
- AE artifact handoff summary aligned to `ae_artifact_handoff.v1`.
- AG audit summary aligned to `ag_generation_audit_event.v1`.

The browser shell remains static and uses Node.js standard library for local
serving. Backend calls are limited to service readiness checks until a
service-authenticated web mediation path is added.

## Files

- `apps/nex-ae-web/index.html`
- `apps/nex-ae-web/src/main.js`
- `apps/nex-ae-web/src/styles.css`
- `apps/nex-ae-web/package.json`
- `tests/test_nex_ae_web_static.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
npm --prefix apps/nex-ae-web run dev
```

Regression tests cover required DOM anchors, mock generation/artifact/audit
state wiring, redaction-sensitive static content checks, responsive CSS guards,
and package metadata.
