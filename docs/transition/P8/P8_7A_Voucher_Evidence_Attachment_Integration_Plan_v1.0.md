# P8.7A Voucher Evidence Attachment Integration Plan v1.0

**Status:** CLOSED THROUGH P8-S75H

**Date:** 2026-10-23

**Phase:** P8.7A - Voucher Evidence Attachment Integration

**Predecessor:** P8.7 Dual Approval Separation Closure

**Successor:** P8.8 Reliability / Reconciliation Closure

---

## 1. Purpose

P8.7A adds practical Voucher evidence attachment handling without reopening the
closed P8.7 approval-domain decision.

The user must be able to select multiple receipts, contracts, images, PDFs, or
opaque ZIP files from the IA surface and bind them to the exact Voucher write
intent that is reviewed and approved.

```text
IA multiple-file selection
        -> AE owner-scoped attachment intake
        -> immutable RustFS objects
        -> canonical AttachmentManifest
        -> NSL_WRITE approval lineage
        -> EOS Voucher attachment association
```

P8.7A is deliberately placed before P8.8 so reliability, reconciliation and
cross-tenant fault tests can exercise a real attachment-bearing Voucher.

---

## 2. Existing Source-Backed Baseline

The Platform already provides:

- an authenticated AE single-file multipart upload path for CX ingestion;
- shared S3-compatible object-storage primitives used with RustFS;
- EOS `eos_voucher_draft_attachment` persistence;
- EOS support for zero to twenty attachment entries in a Voucher command;
- tenant, purpose, object state, immutability, hash, size and media-type
  validation through the EOS `ObjectRefResolver` boundary;
- atomic Voucher and attachment metadata persistence;
- post-write projection of attachment count and stable metadata.

The following gaps remain:

- IA has no multiple-file composer experience;
- the existing AE upload route is a CX document-ingestion path, not a Voucher
  evidence path;
- there is no durable AE attachment batch or approval-locked manifest;
- RustFS does not yet expose an owner-issued Voucher evidence object reference
  through a production resolver used by EOS;
- the current upload facade reads one complete file into memory;
- attachment manifest identity is not yet bound to NSL approval and EOS commit;
- actual RustFS plus AE/WC/OA/EOS protected acceptance has not been performed.

---

## 3. Ownership Decision

| Concern | Owner |
|---|---|
| IA selection, progress and pre-submit removal | AE Web |
| authenticated attachment intake and batch lifecycle | AE API |
| authorized owner/reviewer preview and download | AE API with WC/OA authority |
| binary object and immutable object version | RustFS through AE-owned storage |
| human NSL WRITE decision | WC |
| decision-time authority | OA |
| protected ApprovalRequest and Platform ApprovalEvidence | AE |
| committed Voucher attachment association | EOS |
| optional later document extraction or RAG ingestion | CX, only by explicit request |

Rules:

1. Voucher evidence upload SHALL NOT automatically create a CX document.
2. EOS SHALL persist metadata and opaque references, never attachment bytes,
   storage credentials, presigned URLs or filesystem paths.
3. WC SHALL not own or copy attachment bytes.
4. `object_ref` SHALL be owner-issued and opaque. EOS SHALL resolve it through
   an authenticated service boundary before mutation.

---

## 4. Approval Integrity Decision

An approval applies to one immutable canonical attachment manifest.

Each manifest item binds at least:

```text
attachment_id
object_ref
object_version_ref where available
display_name
media_type
size_bytes
content_sha256
evidence_ref where available
```

Items SHALL be sorted by stable attachment identity before canonical hashing.
The resulting `attachment_manifest_hash` SHALL be included in the governed
business payload and therefore in:

```text
PayloadHash
WriteIntentHash lineage
ApprovalRequest
Platform ApprovalEvidence
EOS create command
post-write verification
```

After approval publication, the batch becomes locked. Adding, removing,
renaming or replacing a file creates a new manifest and requires a new
approval. A display-name change is treated as a manifest change because the
name is part of the human-reviewed evidence projection.

---

## 5. Initial Safety Boundary

- The existing EOS maximum of twenty attachments remains the initial limit.
- Per-file and per-batch byte limits SHALL be configuration-driven and frozen
  in P8-S75A before implementation.
- Upload SHALL be streamed or spooled with bounded memory; one browser batch
  SHALL NOT be loaded into process memory as one byte array.
- Server-side SHA-256 and media-type validation are authoritative.
- A ZIP file is stored as opaque evidence and SHALL NOT be automatically
  expanded, indexed or sent to an LLM in P8.7A.
- Raw attachment content SHALL NOT be sent to an LLM or NSL. Only the safe
  canonical manifest is part of planning and controlled WRITE unless a later
  explicit extraction workflow is approved.
- Unsafe names, path traversal, executable masquerading, hash mismatch,
  oversized content and unsupported media policy SHALL fail closed.
- The lifecycle SHALL represent at least `UPLOADING`, `READY`, `QUARANTINED`,
  `FAILED`, `LOCKED` and `REMOVED` semantics.
- Only `READY` items may enter a manifest. `LOCKED` items remain immutable for
  the Voucher evidence retention period.
- A pluggable malware-scan admission port may be added. Profiles requiring an
  external scanner SHALL fail closed when it is unavailable.

OCR, receipt field extraction, contract summarization, ZIP inspection and
automatic CX ingestion are deferred.

---

## 6. Implementation Slices

The canonical P8-S76 numbering remains unchanged. P8.7A uses additive lettered
Slice identifiers after P8-S75.

### P8-S75A - Source-Backed Attachment Contract Closure

- freeze file count, byte, media and archive policies;
- freeze AE, RustFS and EOS ownership boundaries;
- define attachment batch, item, object resolution and manifest contracts;
- define post-lock mutation and approval invalidation rules;
- audit reusable AE upload and shared object-storage code before refactoring.

**Exit:** contracts and negative examples are accepted before persistence work.

### P8-S75B - Durable AE Attachment Batch and Item Persistence

- add the smallest durable AE model for owner-scoped batches and items;
- preserve tenant, owner, conversation/interaction, state and trace lineage;
- make create/get and exact replay idempotent;
- keep table names concise, with candidate names
  `ae_voucher_attach_batch` and `ae_voucher_attachment`;
- add SQLite regression and actual `nex_ae_test` migration smoke.

**Exit:** restart restores the same batch and item identities.

### P8-S75C - RustFS Immutable Evidence Storage and Resolver

- add bounded streaming or spooled immutable upload support;
- issue opaque object references while keeping bucket/key/credentials private;
- implement the authenticated resolver consumed by EOS;
- verify tenant, purpose `EOS_VOUCHER_ATTACHMENT`, state, version, hash, size,
  media type and immutability;
- define abandoned, failed and unreferenced-object cleanup without deleting a
  locked or committed object.

**Exit:** actual RustFS put/head/resolve/read/delete lifecycle passes with zero
credential or storage-path disclosure.

### P8-S75D - AE Multiple-File Intake API and Batch Lifecycle

- add authenticated Voucher evidence batch APIs separate from CX upload;
- upload files independently under one batch for bounded retries;
- expose safe progress, retry and pre-lock removal operations;
- provide a protected streaming preview/download gateway for the owner and the
  currently authorized approval reviewer without exposing a stable storage
  credential or presigned URL;
- enforce OA-backed tenant/owner scope and configurable limits;
- reject partial, quarantined or failed batches at finalize time.

**Exit:** zero, one and many-file API behavior and duplicate upload replay pass.

**Gate:** run the P8.7A Checkpoint Gate after P8-S75D.

### P8-S75E - Canonical AttachmentManifest and Approval Binding

- build a deterministic sorted manifest and semantic hash;
- propagate batch and manifest identity into WorkIntent and executable plan;
- include attachment bindings in NSL governed payload, ApprovalRequest and
  Platform ApprovalEvidence;
- lock the manifest before approval publication;
- require new approval after every material manifest change.

**Exit:** reorder is deterministic, mutation changes the hash, and stale
approval evidence fails closed.

### P8-S75F - EOS Attachment Admission and Verification Hardening

- pass the exact approved manifest through the EOS write adapter;
- complete production resolver wiring;
- preserve atomic Voucher plus attachment metadata commit;
- verify committed attachment identities during post-write verification and
  reconciliation;
- preserve exactly-once behavior for duplicate commands and response loss.

**Exit:** no attachment substitution, omission or cross-tenant association can
produce a committed Voucher.

### P8-S75G - IA Multiple-File Voucher Evidence UX

- add multiple selection and drag/drop to the authenticated IA composer;
- show per-file progress, READY/failed state, retry and removal before submit;
- show the approved attachment manifest in NSL WRITE and BUSINESS_FORMAL
  review surfaces without exposing object storage internals;
- allow an authorized reviewer to open or download each attachment through the
  protected AE gateway;
- lock editing after approval submission and require a new approval version
  for later changes;
- return to the login surface immediately on session expiry.

**Exit:** keyboard-accessible responsive UI and Playwright acceptance pass.

### P8-S75H - Protected Attachment Journey and P8.7A Closure

- run actual RustFS plus AE, WC, OA and EOS PostgreSQL test databases;
- execute multiple image/PDF/opaque ZIP attachment upload;
- complete IA -> NSL approval -> EOS Voucher commit -> verification;
- test duplicate upload, retry, restart, hash tamper, post-lock mutation,
  cross-tenant object reference and partial-batch rejection;
- verify one Voucher, exact attachment count and zero smoke residue;
- record the P8.7A closure and P8.8 reliability handoff.

**Gate:** run the Repository Full Gate and close P8.7A only after the protected
journey passes with zero skip.

---

## 7. Gate and Environment Plan

| Point | Required gate |
|---|---|
| After P8-S75D | P8.7A Checkpoint Gate |
| P8-S75C onward | actual RustFS protected smoke where applicable |
| P8-S75B onward | actual AE PostgreSQL migration/state smoke |
| P8-S75F onward | actual AE/WC/OA/EOS PostgreSQL integration smoke |
| P8-S75G | authenticated Playwright smoke |
| P8-S75H | protected E2E plus Repository Full Gate |

Remote embedding, reranking and generation providers are not required for the
attachment boundary itself. A live generation provider may be used only for an
optional natural-language Golden A rerun; deterministic fixture planning must
remain sufficient for the mandatory attachment acceptance.

---

## 8. Stop-the-Line Conditions

Implementation SHALL stop for a design decision if any of the following is
required:

- attachment bytes must be stored in PostgreSQL;
- EOS must receive RustFS credentials, bucket keys or presigned URLs as stable
  identity;
- an approved manifest can be changed without new approval;
- CX ingestion becomes implicit for every Voucher attachment;
- cross-tenant ownership can be inferred only from an object-reference string;
- retries can create a second business attachment or Voucher mutation;
- a required scanner or resolver fails open;
- the implementation requires changing the three approval-domain meanings
  closed in P8.7.

---

## 9. P8.7A Exit Gate

P8.7A may be marked `CLOSED` only when:

```text
multiple-file IA selection works
all committed files are immutable RustFS objects
AttachmentManifest is deterministic and approval-bound
post-lock changes require new approval
EOS resolves tenant/purpose/metadata before mutation
Voucher and attachment metadata commit atomically
duplicate/retry/restart does not duplicate business state
cross-tenant and tampered evidence fail with zero mutation
actual RustFS and AE/WC/OA/EOS PostgreSQL protected journey passes
Playwright acceptance passes
Repository Full Gate passes
```

After this gate, P8-S76 may begin and P8.8 fault injection SHALL include at
least one attachment-bearing Voucher scenario.
