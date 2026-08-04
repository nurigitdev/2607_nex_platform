# nex-cx

NeX Content Experience service.

Owned database env: `NEX_CX_DATABASE_URL`.

Document ingestion storage defaults:

- Source files: `NEX_CX_SOURCE_STORAGE_ROOT` or `/data/nex-platform/cx/source-files`
- Extracted Markdown: `NEX_CX_EXTRACTED_MARKDOWN_ROOT` or `/data/nex-platform/cx/extracted-markdown`
- Extraction temp: `NEX_CX_EXTRACTION_TEMP_ROOT` or `/data/nex-platform/cx/extraction-temp`

Local source files are stored outside PostgreSQL using a storage key shaped as
`YYYYMMDD/<sha-prefix>/<sha-prefix>/<source-file-id><extension>`. The CX database
stores source file metadata and links only.

Internal persistence boundary:

- Source file records are global byte/storage metadata records keyed by
  `source_sha256`.
- Content object records are tenant/user-owned logical documents keyed by active
  `tenant_id + owner_user_id + source_sha256`.
- Same-owner duplicate uploads return the existing document; different owners
  get distinct document IDs without learning about each other.
- In the mock upload path, `content_text` is materialized to the local source
  file path and verified against `source_sha256`.
- Document summaries use `summary_1000_0`, target 900 chars, and hard limit
  1000 chars so summary text fits within one default retrieval chunk.
- Summary embeddings index the document summary separately from chunk
  embeddings for future document-level similarity features.
- Prompt registry seed `cx.document_summary.default` records the bounded summary
  system prompt and prompt render events for summary jobs.
- The current adapter is in-memory for mock-first testing; PostgreSQL
  write-through is added after migration execution is stable.

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
- `GET /api/v1/documents/{document_id}/summary`
- `POST /api/v1/documents/{document_id}/summary/run`
- `GET /api/v1/documents/{document_id}/summary-embedding`
- `POST /api/v1/documents/{document_id}/summary-embedding/run`
- `GET /api/v1/prompts/bindings`
- `GET /api/v1/prompts/render-events/{prompt_render_event_id}`
- `GET /api/v1/compatibility/generation-rules`
- `GET /api/v1/recovery/generation-policies`
- `GET /api/v1/recovery/generation-policies/{failure_code}`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/run`
- `POST /api/v1/retrieval/context`
- `GET /api/v1/retrieval/context/{retrieval_package_id}`
- `POST /api/v1/generations`
- `GET /api/v1/generations/{cx_generation_id}`
- `GET /api/v1/generations/{cx_generation_id}/structured-draft`
- `GET /api/v1/generations/{cx_generation_id}/events`

Grounded generation validation:

- `GENERAL_ANSWER` generation can run without retrieval.
- `GROUNDED_ANSWER`, `DOCUMENT_SUMMARY`, and `REPORT_GENERATION` require an
  active compatibility rule and a matching `READY` retrieval package reference.
- Structured drafts expose output hashes, short previews, citation validation,
  and retrieval lineage without exposing full model output text.
- Generation progress events expose ordered, redacted polling timelines for AE
  and AG without exposing raw prompts, source text, provider endpoints, or
  token-level output.
- Generation recovery policies classify failure codes and define retry, repair,
  regenerate, warning acceptance, and cancellation actions without exposing raw
  prompts, provider endpoints, model paths, or source documents.
- MO generation failures after prompt packaging are stored as redacted `FAILED`
  CX execution records with `failure` and `recovery_lineage` metadata, so AE/AG
  can inspect retry or repair intent by `cx_generation_id`.
- CX-to-MO remote-mode regression stays in-process: tests configure MO as
  `NEX_MO_PROVIDER_MODE=live`, fake only the remote provider HTTP hop, and prove
  that CX embedding, retrieval reranking, and generation calls still use MO's
  service API without seeing provider URLs or API keys.
- Retrieval reranking is disabled by default. Set `NEX_CX_RERANKER_ENABLED=1`
  and `NEX_CX_RERANKER_ALIAS` or inject a rerank client to let CX retrieval call
  MO `/api/v1/rerank`; otherwise retrieval packages keep `rerank_state` as
  `NOT_APPLIED`.
