# Slice 0069 CX Retrieval Rerank Bridge to MO vLLM

Status: Implemented.

Backlog candidate: `S6-019` CX retrieval rerank bridge to MO direct vLLM mode.

Requirement coverage: `CX-RET-001`, `MO-PROVIDER-001`, `TRACE-PLAT-001`,
`PLAT-FR-007`.

## Scope

Slice 0069 extends the CX retrieval package path so reranking can be supplied by
MO while preserving the existing default `NOT_APPLIED` retrieval behavior.

- CX retrieval routes accept an optional MO rerank client and reranker alias.
- `NEX_CX_RERANKER_ENABLED=1` can opt the route into the default HTTP MO client.
- Rerank results update `rerank_score`, `final_score`, retrieval profile
  metadata, and score summary state.
- The in-process CX-to-MO remote-mode regression now covers embedding,
  retrieval reranking, and generation against MO live mode while faking only the
  final remote provider HTTP hop.

## Profile Policy

OpenAI-compatible/direct vLLM provider mode remains the canonical direction.
Legacy PCX provider request shapes stay isolated in the `dgx_pcx_legacy` profile
from Slice 0067 and are not activated by CX retrieval.

CX still does not expose remote provider URLs or API keys in retrieval packages,
MO responses, or telemetry snapshots.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_cx_retrieval.py tests/test_cx_mo_remote_mode_bridge.py
scripts/quality/run_quality_gate.sh
```
