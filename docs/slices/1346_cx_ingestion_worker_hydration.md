# Slice 1346: CX ingestion worker hydration

## Outcome

- Added latest extraction-artifact and chunk-set repository reads for both
  in-memory regression and SQLAlchemy runtimes.
- Added a restart hydrator that reconstructs the upload registration and job
  from durable content/source/run identities before a worker checkpoint.
- Reloaded extraction metadata from a root-confined Markdown locator and
  verified the full Markdown SHA-256 before use.
- Rebuilt private chunk text from persisted character offsets, then verified
  every chunk SHA-256. Raw chunk text remains absent from PostgreSQL.
- Reloaded the persisted BM25 index using the configured tokenizer and fallback
  profiles, preserving MeCab-to-`korean_mixed_v1` behavior.
- Wired the hydrator into all PostgreSQL MVP checkpoint handlers while
  preserving the `MvpIngestionVectorIndexer` handler identity.

## Guardrails

- Owner, upload, document, and job identities must match the durable run.
- Invalid, absolute, traversal, and symlink-escaping Markdown paths fail closed.
- Missing Markdown is retryable; hash, offset, and lineage conflicts are not.
- Evidence contains only counts and metadata identities. Source, Markdown,
  chunk text, vectors, credentials, and absolute paths are excluded.
- No database table or migration was added.

## Verification

- Focused regression covers restart hydration, source-only state, repository
  latest reads, BM25 fallback, missing artifacts, path escapes, file/hash/offset
  tampering, owner/upload/job conflicts, coordinator wiring, and vector-indexer
  identity: `186 passed`.
- Slice 1346 Checkpoint Gate: `10,676 passed`, `30 skipped`, with statement
  coverage `98.91%` and branch coverage `97.27%`.
- Hydration module and deterministic evidence runner statement/branch coverage
  are each `100.00%`.
- Contract validation passed with `158` schemas, `216` positive examples,
  `186` negative examples, and `7` OpenAPI documents.
- Deterministic evidence passed `10/10` checks with `4` reconstructed chunks
  and `next=1347`.
- Protected PostgreSQL suites were not enabled for this Checkpoint Gate.
- Actual PostgreSQL journey execution remains assigned to Slice 1350.
