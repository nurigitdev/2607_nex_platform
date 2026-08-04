# Slice 0075 Protected Live RAG Smoke Evidence

Status: Implemented.

Backlog candidate: `S7-005` Protected live RAG smoke evidence.

Requirement coverage: `CX-FR-001`, `CX-FR-003`, `CX-FR-004`,
`MO-PROVIDER-001`, `TRACE-CONTENT-001`, `TRACE-MO-001`, `PLAT-FR-007`.

## Scope

Slice 0075 adds a protected live RAG smoke runner:

```bash
./.venv/bin/python scripts/smoke/run_protected_live_rag_smoke.py --summary
```

By default the command returns `SKIPPED` and does not call any network endpoint.
Live execution requires:

```text
NEX_PROTECTED_LIVE_RAG_SMOKE=1
```

The live flow uses the compatible-only DGX profile and runs:

1. CX source upload
2. extraction
3. chunking
4. lexical index
5. embedding index through MO live provider mode
6. retrieval with MO reranking
7. CX grounded generation with `retrieval_package_ref`
8. MO provider telemetry readback

## Safety

The runner applies a temporary process-local environment while it executes and
restores the caller's environment afterward. It requires the compatible provider
request shapes:

- embedding: `openai_embeddings`
- reranking: `rerank`
- generation: `openai_chat_completions`

Saved evidence excludes provider endpoint URLs, API keys, raw source text, raw
prompt text, raw generation output, and embedding vectors. It records safe
lineage IDs, score/rerank state, quality policy ID, generation status, and MO
telemetry counts.

Live evidence, when executed, should be written under `reports/live/`, which is
ignored by git:

```bash
NEX_PROTECTED_LIVE_RAG_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_protected_live_rag_smoke.py \
  --evidence-output reports/live/protected-live-rag-smoke.json
```

## Evidence

```bash
./.venv/bin/pytest tests/test_protected_live_rag_smoke.py
scripts/quality/run_quality_gate.sh
```
