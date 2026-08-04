# Slice 0068 MO Direct vLLM Execution Regression

Status: Implemented.

Backlog candidate: `S6-018` MO direct vLLM execution profile regression.

Requirement coverage: `MO-PROVIDER-001`, `MO-CONFIG-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0068 locks the MO execution adapter around the canonical `dgx_vllm`
profile introduced in Slice 0067.

The regression covers one direct vLLM profile across three capabilities:

- embedding `POST /v1/embeddings`
- reranking `POST /v1/rerank`
- generation `POST /v1/chat/completions`

The test verifies request shapes, model names, API-key header usage, normalized
responses, telemetry counters, and redaction. Endpoint URLs and API keys must
not appear in MO responses or telemetry snapshots.

## Rerank Normalization

vLLM rerank responses may expose scores as `relevance_score` and echoed
documents as either strings or objects. MO now normalizes `document.text` when
that shape is present while preserving the existing MO rerank result contract.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_mo_remote_provider.py tests/test_protected_dgx_live_profile.py
scripts/quality/run_quality_gate.sh
```
