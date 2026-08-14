# nex-cx

NeX Content Experience service.

Owned database env: `NEX_CX_DATABASE_URL`.

Document ingestion storage defaults:

- Source files: `NEX_CX_SOURCE_STORAGE_ROOT` or `/data/nex-platform/cx/source-files`
- Extracted Markdown: `NEX_CX_EXTRACTED_MARKDOWN_ROOT` or `/data/nex-platform/cx/extracted-markdown`
- Extraction temp: `NEX_CX_EXTRACTION_TEMP_ROOT` or `/data/nex-platform/cx/extraction-temp`
- Max upload size: `NEX_CX_MAX_UPLOAD_SIZE_BYTES` or `52428800`

Local source files are stored outside PostgreSQL using a storage key shaped as
`YYYYMMDD/<sha-prefix>/<sha-prefix>/<source-file-id><extension>`. The CX database
stores source file metadata and links only.

Internal persistence boundary:

- Source file records are global byte/storage metadata records keyed by
  `source_sha256`.
- Content object records are owner-scoped logical documents. Slice 0192 freezes
  the future canonical key as `tenant_ref.id + owner_subject_ref.id +
  source_sha256`, where the refs are OA-owned subject identifiers.
- Existing `tenant_id + owner_user_id + source_sha256` behavior remains the
  compatibility key until repository/API wiring consumes OA refs directly.
- Slice 0194 adds decomposed PostgreSQL columns for indexable OA ownership refs:
  `tenant_ref_type/id`, `owner_subject_ref_type/id`, and
  `uploaded_by_subject_ref_type/id` on `cx_content_objects`, plus
  `principal_ref_type/id` and `granted_by_subject_ref_type/id` on
  `cx_content_acl_entries`. Compatibility triggers backfill these columns from
  legacy fields for external compatibility.
- Slice 0195 updates the repository write/read path to normalize
  `ownership_ref` into the decomposed OA ref columns, query active duplicates by
  canonical owner refs, and create owner ACL entries with
  `principal_ref_type/id` plus `granted_by_subject_ref_type/id`. Legacy
  `tenant_id` and `owner_user_id` remain accepted compatibility aliases.
- Slice 0196 updates AE to propagate canonical OA ownership refs to CX upload
  APIs while still sending legacy aliases. CX canonical intake remains the next
  compatibility step.
- Slice 0197 updates the CX upload intake to consume `ownership_ref` directly,
  reject canonical/legacy owner mismatches, persist the canonical ref in upload
  records, and pass `uploaded_by_subject_ref` through to content object/owner
  ACL metadata. Legacy `tenant_id`, `owner_user_id`, and `user_id` aliases stay
  accepted for mock-first compatibility.
- Slice 0200 adds the optional CX upload owner resolver guardrail. The default
  `NEX_CX_UPLOAD_OWNER_RESOLVER_MODE=disabled` preserves local/mock regression
  behavior. Set it to `verify` to require the OA subject registry to resolve the
  upload `ownership_ref` before CX writes source/content metadata.
- Same-owner duplicate uploads return the existing document; different owners
  get distinct document IDs without learning about each other.
- Upload registration accepts `content_text`, `content_base64`, or metadata-only
  `source_sha256 + size_bytes`. Public records expose only hashes, sizes, and
  storage metadata, not raw source bytes.
- In the mock upload path, `content_text` is materialized to the local source
  file path and verified against `source_sha256`; `content_base64` follows the
  same checksum and materialization policy for binary source bytes.
- Slice 0275 freezes the source-file materialization boundary before multipart
  upload wiring: CX is the source-file system of record, AE is a transient
  browser-file facade, AE must not keep long-term source-file copies, and the
  future object storage adapter should preserve the same metadata/link-only
  database contract.
- Slice 0276 hardens source byte materialization: CX rejects `source_sha256`
  mismatches for provided `content_text` or `content_base64` and exposes the
  owner-scoped `cx_source_file_materialization_receipt.v1` read model without
  raw source bytes or local filesystem paths.
- Slice 0277 through Slice 0279 connect that CX byte-materialization boundary to
  the AE multipart upload facade and AE Web `FormData` path. The protected
  Playwright/PostgreSQL smoke verifies browser-selected bytes reach
  `cx_source_files` with checksum materialization confirmed.
- Slice 0280 freezes uploaded-source extraction readiness: verified uploaded
  bytes can feed the local extraction job, write extracted Markdown, and persist
  one extraction artifact through redaction-safe evidence without remote
  provider access.
- Slice 0281 records the source-file reader fallback decision: extraction must
  keep runtime source bytes as the fast path, then fall back to the verified
  materialized local source file when the runtime memory copy is unavailable.
- Slice 0282 implements that fallback. `run_text_extraction_job(...)` now reads
  verified local source files after runtime source bytes are evicted and records
  redaction-safe `source_reader` metadata in extraction results.
- Slice 0283 adds protected PostgreSQL smoke evidence for that path. The smoke
  migrates `nex_cx_test`, uploads a source file, evicts runtime source bytes,
  runs extraction through the job API, and verifies the persisted extraction
  artifact row.
- Slice 0284 freezes the extractor backend gap before real document adapters.
  `nex_cx.extractors` now exposes an explicit backend catalog: Markdown and
  plain text are implemented by the local adapter, while PDF, DOCX, PPTX, and
  XLSX remain recognized placeholder gaps for Slice 0285-0287.
- Slice 0285 closes the PDF gap with the local `pypdf` adapter. PDF uploads now
  extract page text into Markdown through the same `TextExtractor` boundary,
  while DOCX, PPTX, and XLSX remain explicit placeholder gaps for Slice 0286 and
  Slice 0287.
- Slice 0286 closes the DOCX gap with the local `python-docx` adapter. DOCX
  uploads now extract paragraphs and simple tables into Markdown through the
  same boundary, while PPTX and XLSX remain explicit placeholder gaps for Slice
  0287.
- Slice 0287 closes the remaining PPTX/XLSX Office gaps with local
  `python-pptx` and `openpyxl` adapters. The extractor backend catalog now
  reports Markdown, plain text, PDF, DOCX, PPTX, and XLSX as real extraction
  paths with zero placeholder gaps; Slice 0288 should prove those real document
  adapters through PostgreSQL-backed smoke evidence.
- Slice 0288 adds protected PostgreSQL smoke evidence for the real document
  adapters. With `NEX_CX_REAL_DOCUMENT_EXTRACTION_POSTGRES_SMOKE=1` and the
  `nex_cx_test` database URL, the smoke migrates the test DB, uploads
  PDF/DOCX/PPTX/XLSX files, evicts runtime source bytes, runs extraction through
  the job API, verifies persisted `cx_extraction_artifacts`, and cleans up rows.
- Slice 0289 hardens the extracted Markdown contract. Extraction output is
  normalized to LF line endings, trimmed trailing spaces/tabs, and a final
  newline before storage. `run_text_extraction_job(...)` now emits
  `cx_extracted_markdown_normalization.v1` metadata with structure counts and
  validation flags only; raw Markdown body text remains in the private
  extracted Markdown file path.
- Slice 0290 adds protected PostgreSQL smoke evidence for real-document
  processing. With
  `NEX_CX_REAL_DOCUMENT_PROCESSING_PIPELINE_POSTGRES_SMOKE=1` and the
  `nex_cx_test` database URL, the smoke uploads PDF/DOCX/PPTX/XLSX files,
  evicts runtime source bytes, runs the full processing pipeline, verifies
  durable extraction/chunk/index/summary/processing/job rows, and cleans up
  smoke rows.
- Text extraction runs through the `nex_cx.extractors` adapter boundary. The
  local mock adapter performs real UTF-8 Markdown/plain-text conversion and
  PDF page-text, DOCX paragraph/table, PPTX slide/table, and XLSX sheet/table
  extraction.
- Document processing can be run as one idempotent pipeline: extraction,
  chunking, lexical index, embedding index, summary, and summary embedding.
  Existing outputs are recorded as `SKIPPED`; new outputs are recorded as
  `SUCCEEDED`. Processing emits redaction-safe operational events for started,
  succeeded, and failed lifecycle states.
- Document summaries use `summary_1000_0`, target 900 chars, and hard limit
  1000 chars so summary text fits within one default retrieval chunk.
- Summary embeddings index the document summary separately from chunk
  embeddings for future document-level similarity features.
- Prompt registry seed `cx.document_summary.default` records the bounded summary
  system prompt and prompt render events for summary jobs.
- The current adapter is in-memory for mock-first testing; PostgreSQL
  write-through is added after migration execution is stable.
- `nex_cx.persistence_audit.build_cx_persistence_gap_audit()` emits the
  `cx_persistence_gap_audit.v1` checkpoint. It records current memory-only
  surfaces, target migration tables, and private payload boundaries without
  exposing raw source text, chunk text, summary text, provider endpoints, or
  vectors.
- `SqlAlchemyCxContentRepository` persists source file metadata, content object
  metadata, and owner ACL rows behind the existing repository port. It does not
  persist raw source bytes, extracted text, chunk text, summaries, or vectors.
- SQLAlchemy-backed upload regression preserves owner-scoped duplicate behavior:
  same owner and same `source_sha256` returns `ALREADY_EXISTS`, while different
  owners get separate content objects that share one source file metadata row.
- `nex_cx.source_ownership.build_source_ownership_boundary_decision()` records
  the Slice 0192 ownership decision: CX should keep `cx_source_files` as global
  source metadata, attach ownership to logical content/ACL rows, and consume a
  minimal `nex-oa` stable subject registry before the durable owner-ref schema
  migration.
- Extraction results now write through to `cx_extraction_artifacts` when the
  repository supports it. The persisted artifact stores lineage, extractor
  version, Markdown hash, storage URI, and counts only; Markdown body text stays
  in the extracted Markdown file path.
- Chunk sets now write through to `cx_chunk_sets` and `cx_chunks` when the
  repository supports it. Persisted chunk rows store lineage, policy, offsets,
  hashes, counts, and short previews only.
- Full chunk text remains in `ContentIngestionStore.chunk_texts` for mock-first
  testing and is not written to the public metadata tables.
- Lexical index records now write through to `cx_lexical_terms` and
  `cx_lexical_postings` when the repository supports it. Persisted rows store
  tokenizer metadata, terms, document frequency, chunk references, and
  occurrence counts only.
- Chunk embedding index records now write through to `cx_chunk_embeddings` when
  the repository supports it. Persisted rows store provider/model lineage,
  vector dimension, embedding hash, optional storage URI, status, and trace
  metadata only. Raw vectors remain in the private embedding vector boundary.
- Document summary records now write through to `cx_document_summaries` when the
  repository supports it. Persisted rows store summary hashes, storage URI,
  limits, status, prompt/model lineage, and trace metadata only; full summary
  text remains in the private summary text boundary.
- Summary embedding records now write through to
  `cx_document_summary_embeddings` when the repository supports it. Persisted
  rows store provider/model lineage, vector dimension, embedding hash, optional
  storage URI, status, and trace metadata only. Raw summary vectors remain in
  the private summary embedding vector boundary.
- Retrieval package metadata now writes through to `cx_retrieval_packages` and
  `cx_retrieval_evidence_items` when evidence lineage points at persisted
  content/chunk rows. The persisted rows store query/evidence SHA-256 hashes,
  bounded previews, policy lineage, permission snapshot hash, scores, final
  score, and source summary; raw query text, raw evidence text, and raw query
  vectors stay outside durable public rows.
- Processing run database schema, repository adapter, runtime store
  write-through, PostgreSQL smoke evidence, persisted read-model query helpers,
  and service API read wiring are present.
  `build_cx_persistence_gap_audit()` exposes the planned
  `cx_document_processing_runs` / `cx_document_processing_steps` mapping,
  minimum metadata, private payload policy, and latest safe persistence preview.
  `GET /api/v1/documents/{document_id}/processing` prefers persisted
  repository rows when available and falls back to the in-memory runtime record
  for local regression mode and pre-persistence records.
  Optional header-table decisions for zero-token lexical and zero-chunk
  embedding index history remain deferred.

- Chunk policy: `chunk_1000_100`
- BM25 tokenizer: `mecab_ko`, fallback `korean_mixed_v1`
- Lexical index records include a tokenizer profile. Retrieval query
  tokenization follows each index's recorded tokenizer and falls back to the
  recorded fallback tokenizer before using the built-in mixed tokenizer for
  legacy records.

Current endpoints:

- `GET /health`
- `GET /ready`
- `GET /version`
- `GET /internal/v1/auth/service-claim`
- `POST /api/v1/documents/uploads`
- `GET /api/v1/documents/{document_id}`
- `GET /api/v1/documents/{document_id}/source-file/materialization`
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
- `GET /api/v1/documents/{document_id}/processing`
- `POST /api/v1/documents/{document_id}/processing/run`
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

Document detail:

- `GET /api/v1/documents/{document_id}` returns
  `cx_document_detail_projection.v1`, scoped by `tenant_id` and
  `owner_user_id` query parameters. Missing, inactive, and wrong-owner
  documents are collapsed to the same not-found response, and raw source,
  summary body, embedding vectors, and local storage paths are excluded.
- Slice 0210 hardens the detail contract with
  `document_detail_projection.v1.schema.json`, a valid fixture, a negative
  storage-path leak fixture, and OpenAPI query parameters marked as required.
  Legacy repository rows without embedded `ownership_ref` are projected back to
  canonical OA tenant/subject refs from indexed owner columns.

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
- Retrieval quality policy v1 is recorded in each retrieval package. Defaults
  keep the current scoring behavior: BM25 weight `0.85`, embedding-presence
  weight `0.15`, embedding-presence score `0.5`, low-confidence threshold
  `0.2`, and rerank candidate limit `50`. Tests and future tenant policies can
  pass bounded overrides through `retrieval_policy`.
- CX maps the active AG retrieval policy registry record into runtime retrieval
  settings. Default packages therefore show `policy_source=ag_registry_active`
  plus the registry policy version and hash. Explicit bounded overrides show
  `policy_source=request_override`.
- Retrieval packages expose `bm25_tokenizer_profile` so AG/debug tooling can
  inspect the BM25 tokenizer, fallback, dictionary profile, and query tokenizer
  policy used by the searched lexical index.
- `weighted_rrf_vector_bm25_v1` is available as an opt-in retrieval policy. It
  combines vector cosine rank and BM25 rank with default weights `0.7` and
  `0.3`, RRF `k=60`, and candidate limits of `80` each. If no
  `query_embedding` is supplied, it degrades to BM25-only RRF. Retrieval
  packages record only the query embedding hash and dimension, never the raw
  query vector.
- Protected live RAG smoke evidence is available through
  `scripts/smoke/run_protected_live_rag_smoke.py`. It is skipped by default and
  only calls live providers when `NEX_PROTECTED_LIVE_RAG_SMOKE=1` is set.
- CX retrieval PostgreSQL smoke evidence is available through
  `scripts/smoke/run_cx_retrieval_postgres_smoke.py`. It is skipped by default
  and only writes to the CX test database when
  `NEX_CX_RETRIEVAL_POSTGRES_SMOKE=1` is set with the `test` profile.
- CX upload ownership PostgreSQL smoke evidence is available through
  `scripts/smoke/run_cx_upload_ownership_postgres_smoke.py`. It is skipped by
  default and only writes to the CX test database when
  `NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE=1` is set with the `test` profile.
- CX document detail PostgreSQL smoke evidence is available through
  `scripts/smoke/run_cx_document_detail_postgres_smoke.py`. It is skipped by
  default and only writes to the CX test database when
  `NEX_CX_DOCUMENT_DETAIL_POSTGRES_SMOKE=1` is set with the `test` profile.
- CX processing PostgreSQL operational event evidence is available through
  `scripts/smoke/run_cx_processing_postgres_event_smoke.py`. It is skipped by
  default and only writes to the CX test database when
  `NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE=1` is set with the `test` profile.
- CX processing run PostgreSQL persistence evidence is available through
  `scripts/smoke/run_cx_processing_postgres_persistence_smoke.py`. It is
  skipped by default and only writes to the CX test database when
  `NEX_CX_PROCESSING_POSTGRES_PERSISTENCE_SMOKE=1` is set with the `test`
  profile.
- CX processing service API PostgreSQL evidence is available through
  `scripts/smoke/run_cx_processing_postgres_api_smoke.py`. It is skipped by
  default and only writes to the CX test database when
  `NEX_CX_PROCESSING_POSTGRES_API_SMOKE=1` is set with the `test` profile.
