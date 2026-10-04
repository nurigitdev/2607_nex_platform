# Platform Authenticated Document Upload-to-Index Journey

Status: Active canonical scope for S135.

## Required Outcome

An OA-authenticated user uploads one private document through AE Web/API. AE
derives ownership only from the OA session and hands the source to CX with an
audience-bound service token. CX durably stores the source, admits one
idempotent ingestion job and run, extracts normalized Markdown, chunks it,
builds the lexical index, publishes a fresh vector index through the MO mock
embedding capability, and exposes owner-scoped progress. The journey survives
API and worker restart without losing lineage or exposing private payloads.

## Journey Invariants

- OA remains the sole user and service trust authority. S135 consumes the S134
  trust chain and does not change signing, JWKS, introspection, or revocation.
- AE derives tenant and owner identity from the authenticated OA session in
  protected profiles. Browser-supplied owner aliases never override claims.
- AE owns durable upload handoff metadata but never persists source bytes,
  extracted Markdown, chunk text, embeddings, or provider credentials.
- CX owns source files, extraction artifacts, chunks, lexical indexes, vector
  freshness, durable jobs, ingestion runs, retries, and recovery lineage.
- Source files remain under the configured CX source root. Metadata stores only
  root-relative locators and checksums; paths cannot escape the root.
- Duplicate detection is scoped to tenant, owner, and source SHA-256. A source
  owned by another user is never reused as an authorization shortcut.
- AE-to-CX integration uses HTTP and signed service admission. No service reads
  another service's database.
- S135 uses the MO mock embedding capability for deterministic vector publish.
  Actual embedding and reranker providers are required by S136, not S135.
- Progress and errors are metadata-only. Raw source, Markdown, chunk text,
  vectors, tokens, keys, passwords, and absolute storage paths are forbidden.

## Current Gaps

1. AE upload handoff metadata uses a process-local in-memory store and is lost
   across restart.
2. Legacy local owner defaults remain available outside authenticated request
   handling and must fail closed in protected upload profiles.
3. CX durable jobs and runs survive restart, but ingestion step handlers depend
   on process-local upload state and require repository-backed hydration.
4. The registered CX ingestion background process is a lifecycle shell and does
   not yet claim or execute durable ingestion work.
5. AE does not expose one owner-scoped, restart-safe upload-to-index progress
   projection backed by CX ingestion and vector freshness state.
6. No single protected test proves authenticated upload through index-ready
   completion, restart recovery, denial behavior, and residue-free cleanup.

## Slice Sequence

| Slice | Scope |
| --- | --- |
| `1342` | Freeze the S135 journey boundary, gaps, completion signal, and S136 handoff. |
| `1343` | Fail closed on missing OA owner claims in protected AE upload profiles. |
| `1344` | Persist AE upload handoff metadata and owner-scoped readback in PostgreSQL. |
| `1345` | Harden CX upload admission idempotency and durable source/job/run lineage. |
| `1346` | Hydrate restart-safe extraction, chunking, and BM25 worker state; run Checkpoint Gate. |
| `1347` | Publish a fresh owner-scoped vector index through the MO mock embedding capability. |
| `1348` | Expose AE owner-scoped ingestion progress, failure, retry, and freshness projection. |
| `1349` | Coordinate API/worker restart, recovery, cancellation safety, and cleanup. |
| `1350` | Execute the actual protected PostgreSQL authenticated upload-to-index smoke. |
| `1351` | Harden contracts, privacy, operations, close S135, and run Full Gate. |

## Completion Signal

S135 is complete when an actual OA-authenticated upload traverses AE and CX
over signed HTTP, reaches lexical- and vector-index-ready state through a
durable worker, remains owner-scoped after restart, reports safe progress, and
leaves no test rows or source/private-text files after cleanup. The protected
evidence uses service test databases and the MO mock embedding capability.

## S136 Handoff

S136 inherits only an index-ready, owner-scoped document and its durable
freshness evidence. S136 owns live embedding/reranker execution and
permission-filtered hybrid retrieval acceptance; it must not reopen upload,
source materialization, ingestion durability, or ownership authority.
