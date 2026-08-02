# Slice 0013 CX Chunk Policy 1000 100

Status: Implemented.

Backlog candidate: `S2-003` CX chunk policy implementation.

Requirement coverage: `CX-CHUNK-001`, `CX-EXTRACT-001`, `TRACE-PLAT-001`,
`CONTRACT-CX-001`.

## Scope

Slice 0013 implements the first executable chunk policy for extracted Markdown:

- `chunk_1000_100` uses `NEX_CX_CHUNK_SIZE=1000` and
  `NEX_CX_CHUNK_OVERLAP=100`.
- `POST /api/v1/documents/{document_id}/chunks/run` reads the extracted
  Markdown file and stores chunk metadata.
- `GET /api/v1/documents/{document_id}/chunks` reads the chunk set.
- API responses expose offsets, hashes, counts, and preview text only.
- Full chunk text is retained privately in the local in-memory store for later
  embedding/indexing slices.

The implementation validates that chunk overlap is non-negative and smaller
than chunk size, preventing infinite-progress policy errors.

## Contract Artifacts

- `contracts/schemas/service/nex_cx/chunk_set.v1.schema.json`
- `contracts/examples/retrieval/cx_chunk_set.mock_success.json`
- `contracts/tests/negative/retrieval/cx_chunk_set.raw_text_leak.json`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

The regression tests cover exact offset behavior, short and empty text,
invalid chunk policy values, private chunk text storage, missing extraction,
missing Markdown file, authentication failures, and API readback.
