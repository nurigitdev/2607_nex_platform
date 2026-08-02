# Slice 0016 CX Lexical Index Tokenizer Fallback

Status: Implemented.

Backlog candidate: `S2-006` CX BM25 tokenizer fallback and lexical index shell.

Requirement coverage: `CX-BM25-001`, `CX-CHUNK-001`, `TRACE-PLAT-001`,
`CONTRACT-CX-001`.

## Scope

Slice 0016 adds a lexical index shell for BM25-style retrieval:

- `POST /api/v1/documents/{document_id}/lexical-index/run` builds postings from
  private chunk text.
- `GET /api/v1/documents/{document_id}/lexical-index` reads the lexical index.
- CX requests tokenizer `mecab_ko` by default.
- If MeCab is unavailable, CX falls back to `korean_mixed_v1`.
- The response records requested tokenizer, used tokenizer, fallback tokenizer,
  fallback flag, postings, and trace metadata.

The `korean_mixed_v1` fallback tokenizes Hangul runs and ASCII alphanumeric
runs, lowercasing ASCII terms. This keeps local mock tests independent from
machine-level MeCab installation while preserving the production preference.

## Contract Artifacts

- `contracts/schemas/service/nex_cx/lexical_index.v1.schema.json`
- `contracts/examples/retrieval/cx_lexical_index.mock_success.json`
- `contracts/tests/negative/retrieval/cx_lexical_index.raw_chunk_text_leak.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover tokenizer success, fallback, unsupported tokenizer
failure, postings counts, missing chunk text, missing chunk set, endpoint auth,
API readback, and raw chunk text redaction.
