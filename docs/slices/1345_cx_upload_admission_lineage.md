# Slice 1345: CX upload admission durable lineage

## Outcome

- Reused the original `cx_content_objects.upload_id` when the same owner uploads
  the same source after an API restart.
- Reconstructed the deterministic ingestion job identity from persisted source
  and content metadata, then rebound process-local state to the canonical job
  returned by the durable queue.
- Converged a concurrent content insert race on the already-persisted upload,
  job, and ingestion run instead of admitting duplicate work.
- Kept duplicate detection scoped to tenant, owner, and source SHA-256. Another
  owner receives a distinct content object even when physical source metadata
  is deduplicated by checksum.
- Failed closed when a persisted content object points to missing source-file
  lineage.

## Persistence Decision

No new table or migration is needed. The canonical identity is already split
across `cx_content_objects.upload_id`, the service Job Queue, and
`cx_ingest_runs`. Slice 1345 reconnects these existing records after restart;
Slice 1346 owns repository-backed extraction, chunk, and lexical worker input
hydration.

Private source bytes remain only in the CX source-file boundary. Content, job,
run, and evidence records contain metadata only.

## Verification

- Focused regression covers same-process duplicate, API restart, concurrent
  insert, owner isolation, missing source lineage, and durable admission
  conflicts and safe repository/admission failure responses: `141 passed`.
- Deterministic evidence requires `10/10` checks, one durable ingestion job,
  one durable ingestion run, and `next=1346`.
- CX Slice Gate: `2267 passed`; statement coverage `99.07%`, branch coverage
  `98.15%`; all `5/5` commands passed.
- Changed ingestion module coverage: statement `98.13%`, branch `94.97%`.
  Evidence runner statement and branch coverage are both `100.00%`.
- Contract validation: `158` schemas, `216` positive examples, `186` negative
  examples, and `7` OpenAPI documents.
- SQLite/in-memory restart regression is used in this Slice. The actual
  `nex_cx_test` protected PostgreSQL journey remains scheduled for Slice 1350.
