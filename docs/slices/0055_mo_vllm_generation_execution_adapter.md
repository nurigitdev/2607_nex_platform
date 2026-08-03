# Slice 0055 MO vLLM Generation Execution Adapter

Status: Implemented.

Backlog candidate: `S6-005` MO vLLM generation execution adapter.

Requirement coverage: `MO-FR-001`, `MO-FR-002`, `MO-FR-004`, `PLAT-FR-006`,
`PLAT-FR-007`, `TRACE-MO-001`.

## Scope

Slice 0055 connects the existing MO generation API to vLLM when
`NEX_MO_PROVIDER_MODE=live`:

- `/api/v1/generations` keeps the existing MO request/response contract used by
  CX.
- MO sends OpenAI-compatible `POST /v1/chat/completions`.
- `messages` are passed through after validation; `prompt` is converted to one
  user message when messages are absent.
- The selected generation profile provides the default vLLM model name, with
  env overrides for model, model revision, deployment ID, and endpoint.
- `response_format={"type":"json_object"}` is forwarded to vLLM; text response
  format stays the default.
- Streaming is rejected for now because the adapter normalizes a single
  non-streaming response.
- vLLM choices, finish reason, usage, and request IDs are normalized into the
  existing MO generation response shape.
- Provider-private caller fields and provider endpoint details remain redacted.

`POST /v1/completions` is intentionally not added yet. Chat Completions remains
the first supported live generation shape.

## Files

- `services/nex-mo/nex_mo/remote_provider.py`
- `services/nex-mo/nex_mo/providers.py`
- `tests/test_nex_mo_remote_provider.py`
- `tests/test_nex_mo_providers.py`
- `.env.example`
- `services/nex-mo/README.md`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_nex_mo_remote_provider.py tests/test_nex_mo_providers.py
scripts/quality/run_quality_gate.sh
```

Generation adapter tests use fake `httpx` responders. Real vLLM endpoint values
and API keys stay outside committed files.
