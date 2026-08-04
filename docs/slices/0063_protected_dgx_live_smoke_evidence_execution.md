# Slice 0063 Protected DGX Live Smoke Evidence Execution

Status: Implemented.

Backlog candidate: `S6-013` Protected DGX live smoke evidence execution.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0063 executed the protected DGX live smoke path introduced in Slice 0062
and aligned MO's remote provider adapters with the currently deployed DGX-PCX
provider request shapes:

- The first protected live run passed local config validation but failed DGX
  preflight for embedding and reranking with HTTP `422`.
- Provider OpenAPI/health checks showed that the embedding and reranker
  services use NeX-PCX custom request bodies, not the generic OpenAI-compatible
  shapes used by the initial preflight assumptions.
- MO now supports both generic shapes and DGX-PCX shapes through env-selected
  `request_shape` values.
- The protected DGX profile defaults to `nex_pcx_embeddings_v1` for embedding
  and `nex_pcx_rerank_v1` for reranking.
- Remote embedding execution now normalizes DGX-PCX `embeddings` responses into
  the existing MO `data[].embedding` response shape.
- Remote reranker execution can send DGX-PCX candidate metadata while keeping
  the existing MO rerank response shape.

The protected live evidence file was written under ignored `reports/live/` and
was not committed. The committed record is this slice note plus regression
tests that prove the redaction and adapter behavior.

## Live Evidence Summary

Protected profile schema: `protected_dgx_live_profile.v1`.

Stage status:

- Local live config: `PASS`
- DGX live preflight: `PASS`

Preflight checks:

- Embedding: `PASS`, validated shape `nex_pcx_embeddings_v1`
- Reranking: `PASS`, validated shape `nex_pcx_rerank_v1`
- Generation catalog: `PASS`, validated shape `openai_models`

Redaction:

- Endpoint URLs and API keys were excluded from the evidence.
- Redaction metadata reported configured env key names only.
- No provider endpoint, API key, or DB password matched the repository secret
  scan.

## Files

- `services/nex-mo/nex_mo/remote_provider.py`
- `scripts/smoke/run_protected_dgx_live_profile.py`
- `tests/test_nex_mo_remote_provider.py`
- `tests/test_protected_dgx_live_profile.py`
- `.env.example`
- `services/nex-mo/README.md`
- `docs/README.md`

## Evidence

Slice evidence:

```bash
./.venv/bin/pytest tests/test_nex_mo_remote_provider.py tests/test_protected_dgx_live_profile.py tests/test_local_live_provider_config.py tests/test_dgx_live_provider_preflight.py
NEX_MO_PROTECTED_LIVE_PROFILE=dgx ./.venv/bin/python scripts/smoke/run_protected_dgx_live_profile.py --output reports/live/protected-dgx-live-profile.json --summary
scripts/quality/run_quality_gate.sh
```

The live command must be executed with endpoint and credential environment
values supplied outside git.
