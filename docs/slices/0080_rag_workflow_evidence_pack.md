# Slice 0080: RAG workflow evidence pack

## Intent

Slice 0080 turns the existing traceable mock flow into a compact RAG workflow
evidence pack. The flow now proves that ingestion, extraction, chunking,
embedding, lexical indexing, retrieval policy application, weighted RRF probing,
AE orchestration, CX generation, MO execution, and AG readiness remain connected
under one trace.

## Evidence Shape

`scripts/smoke/run_traceable_mock_flow.py` now emits `rag_workflow` with:

- `workflow_schema_version = rag_workflow_evidence.v1`
- document lineage summary
- active retrieval policy source, version, hash, and ranker mix
- weighted RRF probe policy and ranker settings
- tokenizer profile used by retrieval
- active retrieval package summary
- weighted retrieval package summary
- query embedding snapshot hash, never raw vector values
- generation lineage back to the active retrieval package
- workflow assertions

## Runtime Policy

The flow keeps generation grounded on the active policy retrieval package. It
also runs a separate weighted RRF retrieval probe using
`weighted_rrf_vector_bm25_v1` and a mock query embedding to prove that the new
ranker path is executable without changing the active runtime default.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_traceable_mock_flow.py tests/test_nex_cx_retrieval.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
