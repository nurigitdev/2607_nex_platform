# Slice 0298: Remote Provider Live Timeout Profile

## Scope

Harden MO remote-provider live timeout settings without requiring live DGX
network access.

Slice 0297 showed that the previous shared `5s` timeout can be too tight for
large vLLM generation. This slice separates timeout defaults by provider
capability and keeps the old shared env var as a fallback for compatibility.

## Implemented

- Added capability-specific timeout env vars:
  - `NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS`;
  - `NEX_MO_REMOTE_RERANKER_TIMEOUT_SECONDS`;
  - `NEX_MO_VLLM_TIMEOUT_SECONDS`.
- Raised default live remote-provider timeouts from the previous shared `5s`
  baseline to:
  - embedding: `15s`;
  - reranking: `15s`;
  - vLLM generation: `60s`.
- Preserved `NEX_MO_LIVE_TIMEOUT_SECONDS` as a shared fallback when a
  capability-specific timeout is not configured.
- Added timeout metadata to safe preflight and execution config summaries so
  operators can see the resolved timeout without exposing endpoints or keys.
- Added mock regression coverage for defaults, shared fallback, per-capability
  overrides, invalid capability timeout values, local config snapshots, and
  request timeout propagation.

## Evidence

- Python regression:
  `./.venv/bin/pytest tests/test_nex_mo_remote_provider.py tests/test_local_live_provider_config.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Live DGX smoke was intentionally not run for this slice because remote
providers were not reachable from the current home network. Re-run the
protected live provider/RAG smokes from the office network before treating the
new timeout profile as live-evidence-confirmed.
