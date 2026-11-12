# NeX MyBee W30-CA02: Project Application, Business Code, Lifecycle, and PA Contract Closure v1.0

## 1. Status And Authority

- Decision date: `2026-11-12`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `57f0eeea7ce62e018343a7af0fefea7f9aed9223`
- Runtime code changes by this document: none

This controlled amendment is the mandatory entry contract before `S3-01`.
It takes precedence over the earlier MyBee Phase-1 documents only for:

- Project application and approval-based creation;
- user-facing Project identifiers and annual code allocation;
- Project lifecycle and Project Agent synchronization;
- mandatory approved-Project attribution for new MyBee accounting writes;
- the EOS migration reservation previously assigned to `S3-01` by W30-CA01.

W30-S00 remains closed. Its scoped `DOCUMENT_SIGNOFF` evidence and envelope
path is reused and hardened by this amendment; it is not replaced. All other
trust, proof-domain separation, accounting, privacy, and compatibility rules
remain in force unless this document explicitly changes them.

## 2. Source-Backed Current State

| Boundary | Confirmed implementation | Required correction |
| --- | --- | --- |
| EOS Project identity | `eos_project.project_id` is UUID; `project_code` is an arbitrary tenant-unique string | keep UUID internal; govern request and registration codes |
| EOS Project creation | `PROJECT.PROJECT.CREATE` creates an `ACTIVE` Project and initial owner directly | new product writes must use application and committee approval only |
| EOS Project state | `ACTIVE`, `INACTIVE` | add the approved lifecycle without weakening legacy reads |
| Voucher v1 | `eos_voucher_draft.project_id UUID NOT NULL` | preserve v1 and expose an admitted registration code |
| MyBee proposal | `COMPANY`, `PROJECT`, and `PROJECT_SET` are admitted | prohibit an empty Project set for new MyBee accounting writes |
| W30-S00 envelope | immutable Project UUID bindings exist; registration code is not persisted | bind approved Project code and UUID together |
| AE Agent Registry | PA requires `project_id`; one ACTIVE PA per tenant/Project; status is `ACTIVE/SUSPENDED/RETIRED` | synchronize PA lifecycle from authoritative EOS events |

Changing the EOS UUID primary key to a business string would break numerous
foreign keys and runtime contracts. The UUID therefore remains the technical
identity. This document makes the immutable registration code the business
identity used by people, IA/NSL inputs, reports, and user-facing APIs.

## 3. Project Identifier Contract

### W30-CA02-ADR-01: Separate Technical And Business Identity

The following names are normative:

| Name | Meaning | Visibility |
| --- | --- | --- |
| `project_id` | immutable EOS UUID and internal FK | service-to-service only |
| `project_request_code` | immutable application code | user-facing before and after approval |
| `project_code` | immutable approved registration code; business Project ID | primary user-facing identifier after approval |

User-facing routes, IA responses, NSL arguments, selectors, approval displays,
reports, P&L projections, audit exports, and error messages MUST use a Project
code. They MUST NOT require a person to copy, recognize, or reason about a
UUID. Internal service contracts may carry the UUID, but user-facing
projections must resolve and display the code.

EOS must provide tenant-scoped exact resolvers for request code and
registration code. Ambiguous, cross-tenant, inactive-for-purpose, or unknown
codes fail closed. Fuzzy matching may assist selection but cannot authorize a
write.

### W30-CA02-ADR-02: Store Both Identities At Audit Boundaries

Project-dependent legal and accounting records store the UUID FK and an
immutable registration-code snapshot. A composite consistency constraint or
equivalent locked admission must prove that both values identify the same
tenant Project.

At minimum this applies to:

- Project application and approved Project lineage;
- business-proposal and approved-document lineage;
- VoucherCandidate revision and its accounting lines;
- PostedJournal lines and Project P&L projections.

Operational child tables may use only the UUID internally when their parent
already stores the immutable pair. Their public projections still expose the
registration code.

## 4. Code Grammar And Annual Allocation

### 4.1 Exact grammar

Tenant code is exactly four uppercase alphanumeric characters.

```text
Project request code      = <TENANT4>R<YY><NNNN>
Project registration code = <TENANT4><PURPOSE><YY><NNNN>
```

Purpose codes are frozen as:

| Code | Purpose |
| --- | --- |
| `D` | Development |
| `M` | Manufacturing |
| `S` | Sales |
| `O` | Operations |
| `I` | Investment |
| `G` | Management |

Examples:

```text
VO00R260001
VO00D260001
```

The serial is four digits, starts at `0001`, and ends at `9999`.

### 4.2 Counter persistence

The allocator uses a tenant-scoped table keyed by:

```text
(tenant_id, code_kind, purpose_type, code_year)
```

`code_kind` distinguishes `REQUEST` and `REGISTRATION`. Request rows use the
reserved purpose marker `R`; registration rows use one of `D/M/S/O/I/G`.
The counter stores `last_serial`, version, and timestamps.

There is no destructive January reset job. The first allocation in a new
calendar year creates a new key and returns `0001`; prior-year rows remain as
audit evidence. Allocation is serialized with PostgreSQL row locking or an
equivalent atomic upsert. Duplicate allocation, serial reuse, rollback drift,
and a value above `9999` fail closed.

Code year is evaluated in `Asia/Seoul`:

- request code year is the DRAFT creation year;
- registration code year is the final approval year.

A cross-year approval may therefore legitimately map request
`VO00R260123` to registration `VO00D270001`.

### 4.3 Immutability

The request code is allocated when the DRAFT application is first persisted,
so users never need its UUID. The registration code is allocated only on a
final approved decision. Codes are never edited or reused. Abandoned or
rejected requests may leave gaps; gap-free numbering is not a correctness
goal.

## 5. Persistence Ownership

EOS owns Project application, Project registration, lifecycle, and code
allocation. The minimum additive structures are:

```text
eos_project_application
  tenant_id, application_id UUID, project_request_code,
  purpose_type, state, applicant, immutable request revisions,
  company/NVT/hierarchy inputs, approval case/evidence lineage,
  submitted_at, decided_at, rejection reason, version, timestamps

eos_project_code_counter
  tenant_id, code_kind, purpose_type, code_year,
  last_serial, version, updated_at

eos_project additions
  project_request_code, purpose_type, origin,
  approval_evidence_ref/hash, agent_sync_state
```

The existing `eos_project.project_code` becomes the canonical registration
code for application-created Projects. New rows use
`origin=APPROVED_APPLICATION` and must satisfy the exact code grammar and both
code requirements. Existing rows use `origin=LEGACY_DIRECT`; no synthetic
request or registration code is fabricated during migration.

The application row remains the authority for DRAFT, SUBMITTED, and REJECTED
history. The Project row is materialized only after final approval and owns
ACTIVE, INACTIVE, CLOSING, and CLOSED state.

## 6. Approval And Creation Boundary

### W30-CA02-ADR-03: WC BUSINESS_FORMAL Is The Committee Workflow

Project approval uses existing WC multi-stage `BUSINESS_FORMAL` workflow and
fresh OA Human authority. EOS remains the business source of truth.

```text
DRAFT application
  -> SUBMITTED immutable revision
  -> WC multi-stage committee decision
  -> fresh OA authority and SoD validation
  -> APPROVE: registration code + EOS Project + lifecycle outbox
  -> REJECT: retained REJECTED application, no Project, no PA
```

Final approval, registration-code allocation, Project insertion, initial
lineage, and lifecycle outbox insertion occur in one EOS transaction. Exact
replay returns the same identities and creates no duplicate Project, code,
evidence, or event. Changed replay fails closed.

The existing runtime `PROJECT.PROJECT.CREATE` operation is retired from the
new product path. It may remain temporarily for controlled legacy fixtures,
migration, and backward-compatible regression, but it must be disabled by
default in installed product runtime and must not be callable by MyBee/IA as
a shortcut.

## 7. Lifecycle State Machine

The admitted user-visible transition matrix is exact:

| Current | Allowed next | PA effect |
| --- | --- | --- |
| `DRAFT` | `SUBMITTED` | none |
| `SUBMITTED` | `ACTIVE`, `REJECTED` | final approval creates and activates PA |
| `REJECTED` | none | none |
| `ACTIVE` | `INACTIVE`, `CLOSING` | active; CLOSING retains the PA |
| `INACTIVE` | `ACTIVE` | suspend, then resume the same PA |
| `CLOSING` | `ACTIVE`, `CLOSED` | active; closure work remains eligible |
| `CLOSED` | none | retire PA; terminal |

Unlisted transitions fail closed. In particular:

- no direct DRAFT to ACTIVE or REJECTED transition;
- no SUBMITTED mutation after the admitted revision is frozen;
- no ACTIVE to CLOSED shortcut;
- no INACTIVE to CLOSING shortcut;
- no CLOSED reopening;
- REJECTED is terminal; a new attempt creates a new application and code.

`ACTIVE` means committee-approved and registered. `BUSINESS_READY` remains a
separate operational gate. An ACTIVE Project may be configured, but protected
Project execution and accounting admission must still satisfy the required
readiness and Project-state policy.

During `CLOSING`, new ordinary work is blocked while closure capabilities such
as cost calculation, outstanding-work reconciliation, artifact summarization,
and final reporting remain eligible. A return to ACTIVE restores ordinary
capabilities. CLOSED allows read/audit only.

## 8. Project Agent Synchronization

### W30-CA02-ADR-04: EOS Lifecycle, AE Agent Identity

EOS owns Project state. AE owns PA identity and runtime status. Cross-database
state is coordinated through a durable EOS outbox and an idempotent AE inbox;
it is not presented as one distributed database transaction.

| EOS event | AE result |
| --- | --- |
| Project becomes ACTIVE for the first time | create exactly one PA and set `ACTIVE` |
| INACTIVE -> ACTIVE | resume the existing PA to `ACTIVE` |
| ACTIVE -> INACTIVE | set PA to `SUSPENDED` |
| ACTIVE -> CLOSING | keep PA `ACTIVE`, apply closure capability policy |
| CLOSING -> ACTIVE | keep PA `ACTIVE`, restore ordinary capability policy |
| CLOSING -> CLOSED | set PA to `RETIRED` |

Lifecycle messages carry tenant, internal Project UUID, registration code,
state/version, profile policy reference, event identity, correlation, and
causation. PA profile selection comes from an admitted product policy or
capability registry; it is not hardcoded in an EOS handler.

`agent_sync_state` records `PENDING`, `IN_SYNC`, or `FAILED`. A Project state
commit and its outbox record are atomic. Until AE ACK establishes `IN_SYNC`,
operations that require a PA fail closed. Retry, duplicate delivery, restart,
and reconciliation must converge without creating a second PA. The existing
one-ACTIVE-PA-per-tenant/Project invariant remains authoritative.

## 9. Mandatory Accounting Project Attribution

### W30-CA02-ADR-05: Every New MyBee Accounting Write Has An Approved Project

The business objective is immediate Project P&L. Therefore every new MyBee
business proposal, approved document, VoucherCandidate, PostedJournal line,
and P&L source must carry an admitted Project UUID and its registration code.

The following rules apply:

1. A request code cannot authorize a document or accounting write.
2. Project state must be ACTIVE at document submission and rechecked at
   accounting admission; CLOSING permits only explicit closure operations.
3. INACTIVE, REJECTED, DRAFT, SUBMITTED, and CLOSED Projects are rejected.
4. Every voucher or candidate is Project-specific. A shared invoice is split
   into Project-specific candidates/vouchers or charged to a real approved
   overhead Project; a synthetic Project is prohibited.
5. Every voucher/candidate references one final ApprovedDocumentEnvelope and
   exact document proof. Direct ungrounded accounting creation is prohibited.
6. Supporting documents may group multiple approved Projects only through an
   explicit non-empty PROJECT_SET. Each resulting accounting record remains
   Project-specific and preserves source-document lineage.
7. `scope_type=COMPANY` with an empty Project set is not admitted for new
   MyBee accounting writes.

This is a controlled change from the earlier company-shared candidate design.
Historical v1 rows and reads remain valid, but that compatibility cannot be
used to create a new project-less MyBee transaction.

## 10. Compatibility And Security

- Existing UUID FKs, Project hierarchy, memberships, company bindings, work
  code sets, assignments, and P8 regression remain intact.
- Legacy direct-created Projects remain readable and operational under their
  admitted historical code; no fake request code is backfilled.
- New user-facing responses redact internal UUIDs unless an operator-only
  diagnostic contract explicitly requires them.
- All code resolution is tenant-scoped and exact-match for authorization.
- Registration code is immutable and cannot be reassigned after Project close.
- Lifecycle changes require current OA authority, expected version, immutable
  evidence, and durable operational events.
- Project state or PA state alone is not permission. OA scope, membership,
  assignment, BusinessReady, and accounting policy checks remain required.

## 11. Migration And Slice Reconciliation

The current EOS migration head is `2530`. W30-CA01's reservation of `2531`
for S3-01 is now a historical plan and is superseded as follows:

| Migration | Owner | Purpose |
| --- | --- | --- |
| `2531_eos_project_application_lifecycle.sql` | `W30-S00A` | application, annual counter, Project code/lifecycle additions, accounting reference foundation |
| `2532_eos_project_application_approval.sql` | `W30-S00B` | Project committee approval state, immutable WC decision ledger, final Project materialization |
| next available AE migration after inventory refresh | `W30-S00C` | PA lifecycle inbox/projection only if current AE tables are insufficient |
| `2533_eos_voucher_candidate_v2.sql` | `S3-01` | immutable Project-specific Candidate/revision/line foundation |

Every implementation Slice must recheck repository migration inventory before
creating a file. This document reserves intent, not proof that a migration has
been created or applied.

Recommended implementation order:

```text
W30-CA02  design closure (this document)
W30-S00A  Project application, code allocator, resolver, lifecycle persistence
W30-S00B  WC committee approval finalizer and direct-create runtime retirement
W30-S00C  EOS lifecycle outbox + AE PA lifecycle consumer/reconciliation
W30-S00D  mandatory Project code on proposal/document/accounting boundaries
W30 entry checkpoint
S3-01     VoucherCandidate v2
```

## 12. Minimum Acceptance

1. User-facing Project journeys complete without displaying or requiring UUID.
2. Concurrent requests allocate unique codes; a new year starts at `0001` and
   prior-year counters remain unchanged.
3. `9999` overflow, invalid tenant/purpose, replay drift, and cross-tenant code
   resolution fail closed.
4. Only a final WC committee approval creates one ACTIVE Project and one
   registration code; rejection creates neither Project nor PA.
5. The exact lifecycle matrix is enforced with optimistic concurrency.
6. PA create/suspend/resume/closure/retire delivery is restart-safe and
   idempotent; one ACTIVE PA per tenant/Project remains true.
7. New MyBee proposal/document/candidate/journal writes without an approved
   Project registration code create zero business mutation.
8. Every candidate and journal preserves exact approved-document lineage.
9. Existing v1/legacy Project and voucher regression remains green.
10. Actual EOS/WC/OA/AE PostgreSQL protected smoke verifies migration,
    concurrency, replay, restart, state transition, and zero residue.

## 13. Closure Statement

W30-CA02 closes the Project application, business-identifier, lifecycle, PA,
and mandatory-accounting-attribution design. It does not claim runtime
completion. `S3-01` must not begin until W30-S00A through W30-S00D and the W30
entry checkpoint have passed.
