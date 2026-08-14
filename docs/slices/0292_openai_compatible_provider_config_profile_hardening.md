# Slice 0292: OpenAI-Compatible Provider Config/Profile Hardening

## Scope

Harden the operator configuration boundary for direct vLLM/OpenAI-compatible
remote providers before wiring more CX/RAG smoke flows to live models.

Slice 0291 proved the current DGX endpoints can execute embedding, reranking,
and generation requests. Slice 0292 makes the local config guard stricter so
canonical `dgx_vllm` work cannot accidentally drift back to legacy NeX-PCX
embedding/reranker request shapes.

## Implemented

- `check_local_live_provider_config.py` now emits
  `remote_provider_profile_policy.v1` in its redacted snapshot.
- The local live config guard now treats `dgx_vllm` as the default profile and
  validates the canonical request shapes:
  - embedding: `openai_embeddings`;
  - reranking: `rerank`;
  - generation: `openai_chat_completions`.
- Legacy PCX request shapes are allowed only when
  `NEX_MO_PROTECTED_LIVE_PROFILE=dgx_pcx_legacy`.
- Unsupported protected profile names now fail before any network call.
- Remote provider timeout values must be positive.
- `run_protected_dgx_live_profile.py` now passes the resolved profile into the
  effective env so `--profile dgx_pcx_legacy` is handled consistently.
- `run_protected_remote_provider_live_smoke.py` now runs the local config guard
  during configuration validation and fails before provider calls on model,
  timeout, or profile-policy mismatches.
- The full quality gate now runs the local live provider config guard in
  skipped-by-default mode.

## Evidence

```bash
./.venv/bin/pytest tests/test_local_live_provider_config.py tests/test_nex_mo_remote_provider.py tests/test_protected_dgx_live_profile.py tests/test_protected_remote_provider_live_smoke.py -q
./.venv/bin/python scripts/smoke/check_local_live_provider_config.py --summary
./scripts/quality/run_quality_gate.sh
```

## Operator Notes

Use `dgx_vllm` for new work. Use `dgx_pcx_legacy` only when intentionally
testing older NeX-PCX request shapes. Provider endpoint URLs and API keys remain
runtime environment values only and must not be committed.
