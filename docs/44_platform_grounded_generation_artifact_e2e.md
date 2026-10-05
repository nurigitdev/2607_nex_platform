# Platform Grounded Generation, Repair, and Artifact Lifecycle E2E

Status: S137 active through Slice 1370.

## Required Outcome

An OA-authenticated owner selects a READY S136 retrieval package and starts an
asynchronous grounded generation through AE. CX must reload and authorize the
package, execute generation through MO, validate citations, perform at most one
citation-only repair, and return a durable owner-scoped handoff. AE must persist
the generated response lineage, create and render an artifact, and expose safe
owner-scoped preview and download surfaces.

## Ownership And Trust Invariants

- OA claims remain the tenant and owner authority across AE, CX, and MO.
- AE owns chat, generated-response lineage, artifact lifecycle, preview, and
  download. CX owns retrieval packages, grounded generation execution, citation
  validation, and bounded repair. MO owns provider routing and execution.
- AE never calls a model provider directly. CX reaches generation only through
  the MO generation capability alias.
- Only a contract-valid READY retrieval package with exact owner, hash,
  calibration, ranking, and evidence lineage may enter grounded generation.
- LOW_CONFIDENCE and NO_ANSWER packages remain generation-blocking decisions.
- Citation repair may run once, must reuse the same retrieval package, and must
  not include the invalid output in its prompt or durable metadata.
- Private retrieval and generated text stay in owner-scoped payload stores.
  PostgreSQL, logs, and closure evidence retain metadata and hashes only.
- Preview and download routes resolve only AE-owned artifact links and never
  expose storage paths.

## Integration Gaps

| Gap | Slice | Completion evidence |
| --- | --- | --- |
| Restart-safe retrieval package materialization for generation | `1363` | Complete: CX reloads hash-only metadata and verified private evidence only after exact owner admission. |
| CX grounded generation runtime composition | `1364` | Complete: sync and async generation share one owner-scoped PostgreSQL retrieval materializer with a local fallback. |
| Citation validation and bounded repair handoff | `1365` | Complete: original and repaired outcomes preserve retrieval identity, exact evidence binding, prompt transition, and validated citation lineage through durable CX handoff. |
| AE generated response lineage integration | `1366` | Complete: AE persists exact metadata-only CX grounding/citation/repair lineage, blocks incomplete grounded READY handoffs before private storage, preserves legacy reads, and passes the Checkpoint Gate. |
| Artifact lifecycle admission and render connection | `1367` | Complete: verified owner-scoped response lineage creates an artifact and durable render job without copying private content into the queue. |
| Preview/download and restart-safe artifact recovery | `1368` | Complete: a fresh AE runtime resolves durable render state and rendered files through owner-scoped, storage-ref-free browser links. |
| Contract, operations, and deterministic E2E evidence | `1369` | Complete: strict grounded-artifact admission contracts and one metadata-only evidence pack prove success, bounded repair, owner/lineage denial, and restart recovery without protected dependencies. |
| Protected PostgreSQL and live generation evidence | `1370` | Complete: actual AE/CX test databases and all three MO provider capabilities completed one authenticated browser-to-artifact journey with restart-safe private structured-draft readback and zero row/file residue. |

## Structured Draft Persistence

S137 uses the owner-private storage decision from Slice 1370. CX serializes the
complete structured draft into its private payload store and writes only an
opaque storage reference, SHA-256, byte size, backend, and private schema
version to PostgreSQL. A fresh runtime must re-authorize the exact tenant and
owner, then verify size, hash, JSON schema, generation id, and draft id before
returning the draft to an admitted service caller.

The public generation read model excludes the private reference. AE receives
only an owner-authorized structured draft through the CX API, and neither AE
nor AG may resolve the CX storage URI directly. The opaque adapter boundary is
compatible with a later local-filesystem-to-object-storage migration.

Slice 1371 hardens contracts and the operator runbook, closes S137, runs the
Full Gate, and activates S138.

## Slice Sequence

| Slice | Scope |
| --- | --- |
| `1362` | Freeze the S137 boundary, gaps, completion signal, and S138 handoff. |
| `1363` | Add owner-scoped restart-safe retrieval package materialization for generation. |
| `1364` | Compose retrieval admission, async generation, worker execution, and durable handoff. |
| `1365` | Bind citation validation and one bounded repair attempt to the exact package. |
| `1366` | Persist AE generated-response lineage and run the Checkpoint Gate. |
| `1367` | Connect verified response lineage to artifact admission and asynchronous rendering. |
| `1368` | Harden preview/download, restart recovery, cancellation, and owner isolation. |
| `1369` | Add contracts, operations evidence, and deterministic cross-service E2E. |
| `1370` | Execute protected PostgreSQL plus live generation-provider E2E evidence. |
| `1371` | Publish the runbook, close S137, run Full Gate, and activate S138. |

## Completion Signal

S137 is complete only when grounded answer and artifact scenarios preserve
retrieval, generation, citation/repair, AE response, artifact, render, preview,
and download lineage across restart; cross-owner and non-READY paths fail
closed; actual test databases and the live generation provider pass; cleanup
leaves no database or file residue; and contracts, privacy checks, and Full Gate
all pass.

## S138 Handoff

S138 receives metadata-safe trace and operations projections only. It must
reconstruct the S137 journey through service APIs and may not read OA, CX, AE,
or MO databases or private payload stores directly.
