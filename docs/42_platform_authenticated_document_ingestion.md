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
   across restart. **Closed in Slice 1344:** protected persistence selects the
   service-local SQLAlchemy store and owner-filtered indexed readback.
2. Legacy local owner defaults remain available outside authenticated request
   handling. **Closed in Slice 1343:** protected upload profiles reject missing
   scope and local placeholders while `local_mock` retains compatibility.
3. CX durable jobs and runs survive restart, but ingestion step handlers depend
   on process-local upload state and require repository-backed hydration.
   **Partially closed in Slice 1345:** duplicate upload admission now restores
   the persisted upload identity and converges on one durable source/job/run
   lineage after API restart or concurrent insert. **Closed in Slice 1346:**
   worker handlers reload content/source, extraction, chunk, private chunk text,
   and BM25 state from repository metadata plus root-confined Markdown files.
4. The registered CX ingestion background process is a lifecycle shell and does
   not yet claim or execute durable ingestion work. **Closed in Slice 1349:**
   the protected worker loads restart recovery state, claims durable ingestion
   jobs, observes checkpoint cancellation, and disposes its database pools.
5. AE does not expose one owner-scoped, restart-safe upload-to-index progress
   projection backed by CX ingestion and vector freshness state. **Closed in
   Slice 1348:** AE joins its durable handoff to owner-scoped CX ingestion and
   vector-readiness APIs and exposes only bounded operational metadata.
6. No single protected test proves authenticated upload through index-ready
   completion, restart recovery, denial behavior, and residue-free cleanup.
   **Closed in Slice 1350:** one opt-in subprocess smoke exercises OA login,
   signed AE/CX/MO HTTP boundaries, the durable worker, restart, denials, and
   residue-free cleanup against all five service test databases.

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

## Implementation Progress

- Slice `1342`: boundary, six baseline gaps, quality cadence, and S136 handoff
  frozen.
- Slice `1343`: protected AE upload owner fallback closed for JSON and multipart
  routes; OA browser claims remain authoritative and signed service callers
  require explicit tenant and owner scope.
- Slice `1344`: AE upload handoff metadata persists through the service-local
  SQLAlchemy runtime with owner-filtered readback and recursive private-payload
  rejection; actual PostgreSQL journey evidence remains assigned to `1350`.
- Slice `1345`: CX duplicate upload admission restores the original persisted
  `upload_id`, deterministically reuses the same job/run lineage after restart
  and concurrent insert, rebinds API state to the durable queue result, and
  fails closed when source lineage is incomplete. No new table is required.
- Slice `1346`: PostgreSQL MVP handlers hydrate restart-safe extraction,
  chunking, and lexical state before every checkpoint. Private chunk text is
  reconstructed from Markdown offsets and verified SHA-256 values rather than
  persisted in the database.
- Slice `1347`: the CX vector checkpoint calls the protected MO mock embedding
  capability with service identity, publishes owner-scoped vector payloads,
  and verifies payload count and fingerprint freshness both after publish and
  before idempotent READY reuse. Missing or unverifiable payloads fail closed
  as retryable worker errors.
- Slice `1348`: AE exposes an authenticated owner-scoped progress endpoint that
  projects ingestion, retry, failure, cancellation, and vector freshness state.
  Cross-owner reads are hidden and `INDEX_READY` requires retrieval-usable
  payload-backed freshness.
- Slice `1349`: the executable CX ingestion process loads its restart plan,
  recovers expired leases, claims durable work, and settles cancellation at
  checkpoint boundaries without leaving a step marked as running.
- Slice `1350`: the protected subprocess smoke performs actual OA login, AE
  upload, CX durable worker processing, MO mock embedding, restart-safe
  progress readback, owner denial, and residue-free test PostgreSQL cleanup.
  It also closes the OA-cookie progress admission gap and binds CX summary
  prompts to the durable database registry instead of process-local UUIDs.

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
