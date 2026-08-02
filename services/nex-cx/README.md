# nex-cx

NeX Content Experience service.

Owned database env: `NEX_CX_DATABASE_URL`.

Document ingestion storage defaults:

- Source files: `NEX_CX_SOURCE_STORAGE_ROOT` or `/data/nex-platform/cx/source-files`
- Extracted Markdown: `NEX_CX_EXTRACTED_MARKDOWN_ROOT` or `/data/nex-platform/cx/extracted-markdown`
- Extraction temp: `NEX_CX_EXTRACTION_TEMP_ROOT` or `/data/nex-platform/cx/extraction-temp`

Local source files are stored outside PostgreSQL using a storage key shaped as
`YYYYMMDD/<sha-prefix>/<sha-prefix>/<document-id><extension>`. The CX database
stores source file metadata and links only.
- Chunk policy: `chunk_1000_100`
- BM25 tokenizer: `mecab_ko`, fallback `korean_mixed_v1`

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `POST /api/v1/documents/uploads`
- `GET /api/v1/documents/{document_id}`
- `GET /api/v1/documents/{document_id}/extraction`
- `GET /api/v1/documents/{document_id}/chunks`
- `POST /api/v1/documents/{document_id}/chunks/run`
- `GET /api/v1/documents/{document_id}/embeddings`
- `POST /api/v1/documents/{document_id}/embeddings/run`
- `GET /api/v1/documents/{document_id}/lexical-index`
- `POST /api/v1/documents/{document_id}/lexical-index/run`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/run`
- `POST /api/v1/retrieval/context`
- `GET /api/v1/retrieval/context/{retrieval_package_id}`
- `POST /api/v1/generations`
- `GET /api/v1/generations/{cx_generation_id}`
