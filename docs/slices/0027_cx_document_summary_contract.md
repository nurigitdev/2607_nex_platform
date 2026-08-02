# Slice 0027 CX Document Summary Contract

Status: Implemented.

Backlog candidate: `S3-007` CX document summary contract and mock summarizer
job.

Requirement coverage: `CX-FR-003`, `MO-FR-002`, `TRACE-PLAT-001`.

## Scope

Slice 0027 adds a mock-first document summary flow:

- `POST /api/v1/documents/{document_id}/summary/run` builds a deterministic
  summary from extracted Markdown.
- `GET /api/v1/documents/{document_id}/summary` reads summary metadata.
- Summary output uses policy `summary_1000_0`, default target 900 chars, and
  hard limit 1000 chars so it fits within one `chunk_1000_100` chunk.
- Public summary metadata exposes hash, preview, limits, and summarizer lineage;
  full summary text stays private for downstream summary embedding.
- Contract schema, success example, and negative leak example are registered in
  the contract quality gate.

## Files

- `services/nex-cx/nex_cx/summaries.py`
- `services/nex-cx/nex_cx/ingestion.py`
- `contracts/schemas/service/nex_cx/document_summary.v1.schema.json`
- `contracts/examples/retrieval/cx_document_summary.mock_success.json`
- `contracts/tests/negative/retrieval/cx_document_summary.raw_summary_leak.json`
- `tests/test_nex_cx_summaries.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover summary normalization, trimming, limit validation,
private summary storage, missing extraction/Markdown errors, endpoint auth, and
contract validation.
