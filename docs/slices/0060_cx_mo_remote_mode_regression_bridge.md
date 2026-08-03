# Slice 0060 CX-to-MO Remote-Mode Regression Bridge

Status: Implemented.

Backlog candidate: `S6-010` CX-to-MO remote-mode regression bridge.

Requirement coverage: `CX-FR-006`, `CX-FR-007`, `MO-FR-001`, `MO-FR-004`,
`PLAT-FR-006`, `PLAT-FR-007`, `TRACE-MO-001`.

## Scope

Slice 0060 adds a deterministic regression bridge between CX and MO live-mode
provider adapters:

- The test builds an in-process MO FastAPI app and configures MO with
  `NEX_MO_PROVIDER_MODE=live`.
- The only mocked hop is MO's remote provider HTTP call; CX still talks to MO
  through MO's service-token-protected API routes.
- CX upload, extraction, chunking, and embedding index creation run through the
  existing CX APIs.
- CX generation calls MO generation through the existing facade and receives a
  normalized vLLM-style generation response.
- MO provider telemetry confirms one embedding request and one generation
  request without exposing provider endpoint URLs.
- A throttled remote generation failure is preserved as a retryable CX failed
  generation record and as a degraded MO telemetry row.
- CX records, MO telemetry, and public responses remain redacted from provider
  endpoint values, API keys, raw prompts in metadata, and raw provider payloads.

This slice intentionally does not require DGX-Spark connectivity. It protects
the cross-service boundary before live credentials are used.

## Files

- `tests/test_cx_mo_remote_mode_bridge.py`
- `services/nex-cx/README.md`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_cx_mo_remote_mode_bridge.py
scripts/quality/run_quality_gate.sh
```

The bridge uses fake `httpx` responses only for the final provider hop, so it
remains deterministic and safe for the default regression gate.
