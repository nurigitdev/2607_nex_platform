# NeX MyBee W30-CA01: W20-to-W30 Entry Reconciliation v1.0

## 1. Status And Authority

- Decision date: `2026-11-11`
- Status: `DESIGN_CLOSED_RUNTIME_ENTRY_CONDITIONAL`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `55597935`
- Machine-readable companion:
  `NeX_MyBee_W30_CA01_Entry_Decision_v1.0.json`

This controlled amendment is a narrow source-backed delta after W20. It takes
precedence over the v1.2 Slice Plan only for W30 entry ordering, migration
reservations, the `MB3-01` wave label, and the `DOCUMENT_SIGNOFF` finalization
boundary. All other PAD, SRS, ownership, trust, and compatibility rules remain
in force.

## 2. Reviewed Current State

| Boundary | Confirmed source state | W30 consequence |
| --- | --- | --- |
| EOS migrations | `2529_eos_approved_document_consumption.sql` is current highest | `2522` is historical and cannot be reused |
| S2-01 envelope | Immutable envelope repository and protected GET exist | W30 may consume only a real, usable envelope |
| S2-02 scoped request | `DOCUMENT_SIGNOFF` and `ACCOUNTING_POSTING` requests and WC publication exist | Request creation is not final approval |
| S2-03 decision | Scoped WC decision admission exists only for `ACCOUNTING_POSTING` | It deliberately rejects `DOCUMENT_SIGNOFF` |
| MB2-01 | Proposal form, request consumer, receipt admission, and envelope read exist | Consumer must not fabricate final proof or envelope |
| Voucher v1 | `FINANCE.CREATE_VOUCHER_DRAFT` and DRAFT-only persistence remain active | W30 is additive v2 and must preserve v1 exactly |
| VoucherCandidate v2 | Candidate modules, migration, routes, and tests do not exist | S3 packet status remains planned |

The packet-level W20 implementations are closed and verified. The integrated
business-proposal journey is nevertheless conditional: a scoped
`DOCUMENT_SIGNOFF` terminal decision cannot yet produce the proof and envelope
that S3-01 must require.

## 3. Normative Decisions

### W30-CA01-ADR-01: Separate Packet Closure From Journey Closure

S2-01 through S2-04 and MB2-01 remain historically closed. Their code and
evidence are not reopened. The W20-to-W30 vertical entry is marked
`CONDITIONAL` until `W30-S00` passes protected integration acceptance.

### W30-CA01-ADR-02: Add W30-S00 Before S3-01

`W30-S00: Scoped Document Signoff Finalization` is mandatory before S3-01.
It will complete this chain:

```text
MyBee proposal revision
  -> EOS scoped DOCUMENT_SIGNOFF case
  -> WC BUSINESS_FORMAL Human decision
  -> fresh OA decision admission
  -> immutable scoped document evidence
  -> ApprovedDocumentEnvelope materialization
```

The transition must be idempotent, restart-safe, tenant-scoped, and exact-hash
bound. A rejection creates neither approval evidence nor an envelope.

### W30-CA01-ADR-03: Keep Proof Domains Separate

The following are prohibited:

- routing `DOCUMENT_SIGNOFF` through the accounting approval service;
- treating accounting evidence as business-document proof;
- manufacturing a generic approval instance with a fake or unrelated Project;
- weakening proof validation or accepting a caller-supplied envelope as proof;
- allowing MyBee to write EOS or WC tables directly.

`W30-S00` must use the existing scoped case and scoped decision lineage, add a
dedicated immutable document-signoff context/evidence boundary, and preserve
the existing generic proof-backed envelope path for compatibility. Any schema
amendment must support exactly one admitted proof source and retain current
GET response semantics.

### W30-CA01-ADR-04: Persist Materialization Inputs Before Decision

The scoped request must persist an immutable, hash-bound document context that
contains the information required to materialize an envelope:

- document identity and revision;
- document type and work code;
- content and attachment-manifest hashes;
- company and Project scope;
- approved amount and currency;
- validity period and optional tolerance policy hash.

WC decision payloads must not be extended into a second business data source.
The terminal event carries decision lineage; EOS resolves materialization data
from its already committed scoped context.

### W30-CA01-ADR-05: Reserve Fresh Migration Numbers

Current migration inventory ends at `2529`. The source-backed reservation is:

| Migration | Owner | Purpose |
| --- | --- | --- |
| `2530_eos_document_signoff_finalization.sql` | `W30-S00` | scoped document context/evidence and envelope proof-source compatibility |
| `2531_eos_voucher_candidate_v2.sql` | `S3-01` | immutable Candidate/revision/line foundation consumed by S3-02/S3-03 |

The reservation is not evidence that either migration exists or has been
applied. Every implementation Slice must recheck HEAD before creating its
migration.

### W30-CA01-ADR-06: Normalize MB3-01 Into W30 Closure

The Markdown plan already groups `MB3-01` with W30. The Execution Matrix's
isolated `W31` label is retained as hash-pinned historical planning input and
is normalized to `W30` by this controlled amendment. Editing the v1.2 matrix
in place would invalidate the admitted FL catalog source-provenance digest.
Implementation order remains:

```text
W30-S00 -> S3-01 -> S3-02 -> S3-03 -> MB3-01
```

MB3-01 remains a consumer-only packet with no migration and no direct GL
write. It may start after S3-01/S3-02 provider contracts are stable, but W30
does not close until S3-03 and MB3-01 both pass.

### W30-CA01-ADR-07: Preserve The No-Posting Boundary

W30 creates and reviews candidates only. A WC approval decision, business
document proof, or accounting evidence cannot set a candidate to `POSTED` and
cannot create a Journal. Immutable Journal creation remains W40.

## 4. Corrected W30 Slice Order

| Order | Slice | Exit condition |
| --- | --- | --- |
| 1 | `W30-S00` Scoped Document Signoff Finalization | actual EOS/WC/OA PostgreSQL journey creates one exact envelope; replay creates none |
| 2 | `S3-01` VoucherCandidate v2 Immutable Revision/Line | `2531` migration, proof-required create, v1 unchanged |
| 3 | `S3-02` Accounting/FX/Period/Balance Validation | deterministic validation, no GL side effect; Checkpoint Gate |
| 4 | `S3-03` Review Submit/Return/Invalidate | CAS state machine, stale proof invalidation, protected PostgreSQL smoke |
| 5 | `MB3-01` MyBee Candidate Consumer | provider-consumer contract and W30 Full Gate |

Remote generation, embedding, and reranker providers are not required for any
of these packets.

## 5. W30-S00 Minimum Acceptance

1. `DOCUMENT_SIGNOFF` routes to a dedicated finalizer; `ACCOUNTING_POSTING`
   continues to route to the existing accounting service.
2. Exact replay returns the original evidence/envelope identities.
3. Changed case, context, decision, policy, OA authority, or document hash
   fails closed.
4. Company, Project, and Project-set scopes do not use a synthetic Project.
5. Rejected, expired, revoked, delayed, or out-of-order decisions create zero
   proof and zero envelope rows.
6. Existing S2-01 generic proof-backed rows remain readable and immutable.
7. Actual `nex_eos_test`, `nex_wc_test`, and `nex_oa_test` protected smoke
   applies current migrations in isolated schemas and leaves zero residue.
8. Existing P8/Golden A voucher v1 payload, hash, DRAFT state, and tests remain
   unchanged.

## 6. Gate Sequence

- W30-S00: focused tests, actual EOS/WC/OA PostgreSQL smoke, Checkpoint Gate
- S3-01: actual EOS PostgreSQL migration/concurrency smoke and `G-V1`
- S3-02: W30 Checkpoint Gate
- S3-03: actual EOS/WC/OA PostgreSQL replay/SoD smoke
- MB3-01: provider-consumer tests, Repository Full Gate, zero-residue check

## 7. Closure Statement

W30-CA01 is complete when this document, its machine-readable companion, the
reading order, and the corrected `MB3-01` wave label agree. It does not claim
the W30 runtime entry gate is open. Runtime implementation starts with
`W30-S00`; S3-01 must not bypass that prerequisite with fixtures or direct
database seed behavior presented as a production journey.
