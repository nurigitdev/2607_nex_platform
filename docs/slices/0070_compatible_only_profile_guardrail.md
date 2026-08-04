# Slice 0070 Compatible-Only Profile Guardrail

Status: Implemented.

Backlog candidate: `S6-020` Compatible-only DGX profile guardrail and legacy
PCX quarantine.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0070 makes the provider profile boundary easier to inspect and harder to
misread.

- Protected DGX profile evidence now includes a migration policy block.
- `dgx_vllm` is marked as the canonical direct vLLM lane for new work.
- `dgx_pcx_legacy` is marked as an explicit legacy compatibility lane only.
- Canonical direct vLLM config summaries no longer show NeX-PCX request option
  defaults.
- NeX-PCX compatibility env keys in `.env.example` are blank and documented as
  legacy-only overrides.

## Current Policy

New work should use OpenAI-compatible/direct vLLM shapes:

- embedding: `openai_embeddings`
- reranking: `rerank`
- generation: `openai_chat_completions`

The older NeX-PCX shapes remain available for rollback or provider compatibility
tests, but only through `NEX_MO_PROTECTED_LIVE_PROFILE=dgx_pcx_legacy` or an
explicit request-shape override in a local environment file.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_mo_remote_provider.py tests/test_local_live_provider_config.py tests/test_protected_dgx_live_profile.py
scripts/quality/run_quality_gate.sh
```
