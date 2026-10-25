# P8-CA05 NVT Project Operations and Batch Membership Contract Closure v1.0

**Status:** DESIGN CLOSURE / P8.11 IMPLEMENTATION ENTRY AUTHORIZED

**Predecessor:** P8-S103 FINAL / P8 v1.1 DEMO BASELINE

**Target Exit:** P8 FINAL AS-BUILT v1.2 / DEMO RELEASE CANDIDATE REFRESH

**Date:** 2026-10-25

## 1. Purpose

P8-S103 closed the first governed Project and Project-membership demonstration
baseline. A rehearsal of the Chairman demonstration identified two practical
gaps:

```text
NVTProject can be persisted internally but has no governed CREATE/GET/LIST/UPDATE path.
Project membership can be added only one person at a time.
```

One approval per employee is not a credible Project setup workflow. The
Platform must accept several employee candidates in one user intent, resolve
them against current OA identity, approve one exact admitted member set, add
the eligible members through one controlled WRITE, and return a deterministic
summary for both successful and rejected candidates.

This document closes that contract before implementation. It does not rewrite
the P8 v1.0 or v1.1 baselines. It authorizes an additive P8.11 sequence and a
later Final As-Built v1.2 closure.

## 2. Source-Backed Current State

### 2.1 NVTProject

EOS already owns:

```text
eos_nvt_project
SqlAlchemyEosProjectRepository.create_nvt_project()
SqlAlchemyEosProjectRepository.get_nvt_project()
SqlAlchemyEosProjectRepository.update_nvt_project()
```

The persisted model already carries:

```text
tenant_id
nvt_project_id
nvt_project_code
name
status
version
created_at
updated_at
```

The source does not yet provide a governed NVTProject service, tenant-scoped
LIST query, protected API, canonical operation registry entry, NSL Skill/Tool,
or IA admission path.

### 2.2 Project membership

EOS already owns:

```text
eos_project_member
single-member ADD / REMOVE / LIST
ACTIVE / REMOVED lifecycle
OWNER / MANAGER / MEMBER / VIEWER roles
reactivation without duplicate relationship rows
last-active-OWNER protection
Project row and membership row locking
OA-backed current subject and authority checks
BusinessOperation / idempotency / outbox transaction ownership
```

The current controlled WRITE `PROJECT.MEMBERSHIP.ADD` accepts one resolved
`target_subject_id`. No batch command, employee-candidate resolver, partial
business outcome, or collection-valued membership Skill exists.

### 2.3 NSL capability

The admitted NSL v0.2.1 strict profile already supports bounded `List<T>`
values. It intentionally enforces:

```text
write_node_count <= 1
WRITE inside FOREACH = forbidden
Approval <-> WRITE = exactly 1:1
```

NSL source does not currently declare arbitrary user-defined record types.
CA05 therefore SHALL NOT introduce a language or runtime version solely to
carry a list of member records. The Platform SHALL use existing collection
types after deterministic candidate resolution.

### 2.4 Frozen-document naming drift

P8 Final As-Built v1.1 contains one prose list using
`PROJECT.PROJECT_MEMBER.*`. The authoritative runtime registry, EOS API, NSL
artifacts, CA04, and persisted evidence use:

```text
PROJECT.MEMBERSHIP.ADD
PROJECT.MEMBERSHIP.REMOVE
PROJECT.MEMBERSHIP.LIST
```

The v1.1 file remains immutable history. CA05 records the prose difference as
documentation drift only. It does not authorize an alias, rename, or migration
to `PROJECT.PROJECT_MEMBER.*`.

## 3. Amendment Boundary

### 3.1 In scope

```text
governed NVTProject CREATE / GET / LIST / UPDATE
NVTProject current-authority and optimistic-version enforcement
one batch Project-membership ADD business command
natural-language employee-number and expected-name candidate intake
OA-owned batch identity resolution
deterministic candidate normalization and duplicate handling
one approval for one exact admitted member set
valid-member application with item-level business outcomes
restart-safe idempotency, verification, audit, and outbox evidence
IA user-safe result summary
actual PostgreSQL and protected demonstration acceptance
```

### 3.2 Out of scope

```text
NVT token economics or incentive calculation
NVT profitability or portfolio optimization
NVTProject membership or separate NVT ACL persistence
Project member bulk REMOVE
CSV or external-directory bulk import
dynamic/custom Project roles
per-item role selection in one batch
automatic fuzzy person matching
name-only identity resolution
cross-tenant Project sharing
multiple NSL WRITE nodes
WRITE in NSL FOREACH
general List<Record> NSL source-language extension
retroactive mutation of P8 v1.0/v1.1 evidence
```

## 4. Ownership Boundary

Ownership remains:

```text
OA
  employee-number alias, subject identity, display name, tenant membership,
  active/inactive state, current scopes, and revocation

AE / IA
  natural-language candidate extraction, deterministic clarification,
  OA resolution orchestration, rejected-candidate presentation, and
  admitted WorkIntent/Plan lineage

NSL
  one bounded collection-valued controlled WRITE, approval binding,
  payload identity, commit evidence, and verification contract

EOS
  NVTProject, Project membership, BusinessOperation, idempotency, outbox,
  authoritative mutation, item outcome, and business verification

WC
  approval work coordination; it does not resolve employee identity or mutate
  Project membership
```

No service SHALL read another service's database directly. OA identity
resolution occurs through a service-token-protected OA API. EOS remains the
only owner allowed to mutate `eos_nvt_project` and `eos_project_member`.

## 5. Canonical Operation Set

P8.11 SHALL add:

```text
PROJECT.NVT_PROJECT.CREATE
PROJECT.NVT_PROJECT.GET
PROJECT.NVT_PROJECT.LIST
PROJECT.NVT_PROJECT.UPDATE
PROJECT.MEMBERSHIP.ADD_MANY
```

The compound action `ADD_MANY` is intentional. It denotes one business
command whose payload contains several relationships. It is not an alias for
repeated `PROJECT.MEMBERSHIP.ADD` calls and it is not a general import API.

Existing operations remain unchanged:

```text
PROJECT.MEMBERSHIP.ADD
PROJECT.MEMBERSHIP.REMOVE
PROJECT.MEMBERSHIP.LIST
```

The new Skill and terminal Tool may share the same canonical operation name
while retaining independent exact version, semantic hash, contract hash, and
artifact identity.

## 6. NVTProject Contract

### 6.1 Identity and immutable fields

NVTProject identity is tenant-scoped:

```text
(tenant_id, nvt_project_id)       primary identity
(tenant_id, nvt_project_code)     unique business identity
```

After CREATE, these fields are immutable:

```text
tenant_id
nvt_project_id
nvt_project_code
created_at
```

### 6.2 CREATE

`PROJECT.NVT_PROJECT.CREATE` SHALL:

1. require fresh OA `project:nvt_project:create` authority;
2. accept a caller-generated UUID, stable code, name, and initial ACTIVE
   status;
3. reject duplicate identity or tenant-scoped code;
4. use one approval and one NSL controlled WRITE;
5. execute through EOS BusinessOperation/idempotency/outbox;
6. verify the created object with canonical GET.

### 6.3 GET and LIST

`PROJECT.NVT_PROJECT.GET` and `PROJECT.NVT_PROJECT.LIST` SHALL require fresh
OA `project:nvt_project:read` authority and tenant scope. NVTProject is a
tenant business catalog object, not a Project-member resource. Project
membership SHALL NOT be invented as an NVT read requirement.

LIST SHALL be bounded and deterministically ordered by:

```text
nvt_project_code ASC, nvt_project_id ASC
```

It SHALL support at least:

```text
status filter
limit
offset
```

Cross-tenant GET returns the same not-found projection as an absent object.

### 6.4 UPDATE

`PROJECT.NVT_PROJECT.UPDATE` SHALL:

1. require fresh OA `project:nvt_project:admin` authority;
2. require `expected_version`;
3. allow only `name` and `status` changes;
4. increment version exactly once per committed semantic change;
5. reject an empty patch;
6. preserve exact replay without another version increment;
7. reject ACTIVE to INACTIVE while an ACTIVE Mother Project directly
   references the NVTProject;
8. allow INACTIVE to ACTIVE under the same fresh authority;
9. use one approval and one NSL controlled WRITE;
10. verify the updated object with canonical GET.

Changing `nvt_project_code` requires a separately designed operation and is
not admitted by CA05.

### 6.5 NVT authorization independence

NVT scopes are distinct from Project membership scopes:

```text
project:nvt_project:create
project:nvt_project:read
project:nvt_project:admin
```

For the demonstration bootstrap, the authorized operator role MAY receive all
three scopes. Granting `project:project:admin` alone SHALL NOT silently grant
NVT administration unless OA role configuration explicitly contains the new
NVT scopes.

## 7. Batch Membership Intake and Resolution

### 7.1 Natural-language candidate shape

The IA-facing candidate is:

```text
employee_id       required candidate key
expected_name     optional human confirmation hint
input_index       original presentation order
```

Employee number is the authoritative lookup alias. A name is never identity
and SHALL NOT be used for fuzzy or name-only matching. When `expected_name` is
present and does not match the current OA display name under the documented
normalization policy, that item is rejected as `NAME_MISMATCH`.

The initial name-confirmation normalization is deterministic:

```text
Unicode NFC
trim leading and trailing whitespace
collapse internal whitespace runs to one ASCII space
Unicode casefold
exact comparison after normalization
```

It does not perform phonetic, edit-distance, alias, transliteration, or token
reordering matches. Employee-number normalization reuses OA's canonical
employee identifier normalization and is not reimplemented by AE or EOS.

### 7.2 OA batch resolution

OA SHALL expose one protected batch resolver that returns, per input item:

```text
input_index
normalized_employee_id
subject_id                 success only
display_name               success only, safe projection
subject_revision           success only
tenant_membership_revision success only
resolution_status
```

OA SHALL distinguish current eligibility internally while preventing
cross-tenant identity enumeration. A candidate absent from the requested
tenant and a candidate that exists only in another tenant receive the same
public `EMPLOYEE_NOT_FOUND` result.

The minimum resolution statuses are:

```text
RESOLVED
INVALID_EMPLOYEE_ID
EMPLOYEE_NOT_FOUND
SUBJECT_INACTIVE
NAME_MISMATCH
DUPLICATE_INPUT
```

Network failure, timeout, malformed OA response, or unverifiable authority is
not an item rejection. It is a retryable operation-level failure.

### 7.3 Canonical admitted set

AE SHALL construct the admitted member set only from `RESOLVED` candidates.
It SHALL:

1. preserve the raw request only in protected interaction/admission lineage;
2. deduplicate by `(tenant_id, subject_id)`;
3. sort the admitted set by `subject_id` using bytewise ascending order;
4. bind the OA resolution evidence hash and revisions;
5. prevent an empty admitted set from entering approval or NSL WRITE.

The controlled payload SHALL contain stable subject authority, not model-
supplied employee identity:

```text
tenant_id
requester_subject_id
project_id
target_subject_ids: List<String>
member_role: String
resolution_evidence_hash
```

For P8.11, `member_role` is one common role for the complete batch and defaults
to `MEMBER`. Per-item roles are deferred.

## 8. NSL Controlled WRITE Contract

`PROJECT.MEMBERSHIP.ADD_MANY` is the first collection-valued governed WRITE in
the Platform. It is not the first Skill with several named arguments and it
does not change NSL's single-WRITE safety model.

The Skill SHALL use existing NSL v0.2.1 types and limits:

```text
target_subject_ids: List<String>
collection_size: 50
tool_calls: 1
write_nodes: 1 (strict-profile invariant)
approval nodes: 1
```

The following are forbidden:

```text
foreach member -> write PROJECT.MEMBERSHIP.ADD
one approval per member
several WRITE nodes in one Skill
runtime-selected WRITE Tool
opaque JSON string as the member collection
parallel employee-id/name lists inside the authoritative WRITE payload
```

The approval request SHALL bind the exact canonical target set, Project,
common role, resolution evidence hash, payload hash, Skill semantic identity,
and expiry. Reordering the same resolved set SHALL NOT create a different
semantic member set because AE must canonicalize it before NSL execution.

Changing any subject, role, Project, or resolution evidence requires a new
payload hash and a new approval.

## 9. Batch Size and Structural Admission

P8.11 maximums are:

```text
raw candidates per request     50
unique admitted subjects       50
common role values             OWNER | MANAGER | MEMBER | VIEWER
default role                   MEMBER
```

These are request-level structural failures and stop before approval:

```text
missing or empty candidate list
more than 50 candidates
malformed request envelope
invalid common role
missing Project identity
empty admitted set after resolution
tampered resolution evidence
```

An empty admitted set produces a user-safe rejected intake summary but does
not create an ApprovalRequest, NSL execution, BusinessOperation, outbox event,
or membership mutation.

## 10. Mutation and Partial Outcome Semantics

### 10.1 One transaction and one command

EOS SHALL process the admitted set as one BusinessOperation and one database
transaction. It SHALL lock the active Project and relevant subject-membership
rows in deterministic subject order.

EOS SHALL re-check, at commit time:

```text
requester current OA authority
requester active OWNER or MANAGER Project membership
requester project:membership:manage scope
target subject current OA eligibility
Project ACTIVE status
existing Project membership state and role
```

Fresh checks cannot be replaced by the earlier resolution snapshot.

### 10.2 Item outcomes

The minimum committed item outcomes are:

```text
ADDED                 new active relationship inserted
REACTIVATED           existing REMOVED relationship reactivated
ALREADY_ACTIVE        same role already active; no row mutation
SUBJECT_INACTIVE      subject became ineligible before commit
ROLE_CONFLICT         active or removed relationship has a different role
NOT_ELIGIBLE          current authoritative eligibility cannot admit the item
```

AE SHALL merge these with pre-admission results such as
`DUPLICATE_INPUT`, `EMPLOYEE_NOT_FOUND`, and `NAME_MISMATCH` for the final user
summary.

### 10.3 Top-level outcomes

The user-safe result status is one of:

```text
APPLIED               every admitted item added or reactivated
PARTIALLY_APPLIED     at least one mutation and at least one rejected item
NO_CHANGE             admitted items were already active with the same role
REJECTED              no candidate was admitted before WRITE; no WRITE occurs
```

`COMMITTED` describes the BusinessOperation commit state. It does not mean
that every candidate was added. Item and aggregate domain outcomes remain
separate from commit state and post-write verification status.

### 10.4 Failure boundary

Expected item business failures may produce `PARTIALLY_APPLIED`. These do not:

```text
OA/network unavailable
database unavailable
transaction serialization failure after retry exhaustion
unexpected constraint or persistence failure
authorization source malformed or unverifiable
payload/approval/evidence tamper
unknown commit state
```

Those failures preserve the existing fail-closed, rollback, retry, or
reconciliation behavior. They SHALL NOT be converted into a successful
partial result.

## 11. Idempotency, Concurrency, and Verification

1. The canonical admitted subject set participates in the NSL-compatible
   payload hash.
2. Exact replay returns the original aggregate and item results without new
   membership mutation.
3. The same idempotency key with a different canonical set fails as conflict.
4. Two concurrent batches targeting the same subject cannot create duplicate
   `(tenant_id, project_id, subject_id)` relationships.
5. A concurrent single ADD and ADD_MANY must resolve to one relationship and a
   deterministic no-op or conflict result, never two rows.
6. Reactivation reuses the existing relationship identity and increments its
   version once.
7. Post-write verification reads the authoritative membership set and proves
   every `ADDED`, `REACTIVATED`, and `ALREADY_ACTIVE` result.
8. UNKNOWN_COMMIT_STATE uses reconciliation and never blindly dispatches a
   new WRITE.

No new membership table is required. The existing `eos_project_member`,
BusinessOperation, idempotency, outbox, and verification structures are
reused.

## 12. Result and Privacy Contract

The public result SHALL include:

```text
operation_status
requested_count
resolved_count
added_count
reactivated_count
unchanged_count
rejected_count
project_id
member_role
item_results
business_operation_id / safe result reference
```

The NSL Skill SHALL emit the aggregate counts, status, and safe result
reference using existing scalar and `List<String>`-compatible types. The
detailed structured `item_results` remain an EOS result projection and are
merged with the AE pre-admission rejection projection for the user response.
CA05 does not encode item records as opaque JSON strings and does not require a
new NSL `List<Record>` source declaration.

Each item result SHALL contain only the minimum safe projection required to
identify the submitted candidate and explain its outcome. Passwords,
credentials, tokens, OA raw profiles, authorization payloads, and secrets are
forbidden.

Employee numbers and display names are classified at least `INTERNAL`. They
SHALL NOT appear in provider prompts beyond the authorized planning boundary,
metrics labels, exception text, unprotected logs, or external notification
payloads. Audit and outbox records SHOULD prefer stable subject references and
aggregate counts.

## 13. API and Transport Contract

The protected EOS route is additive:

```text
POST /internal/v1/projects/{project_id}/memberships:add-many
operation_id = PROJECT.MEMBERSHIP.ADD_MANY
```

The protected NVT routes are:

```text
POST  /internal/v1/nvt-projects
GET   /internal/v1/nvt-projects/{nvt_project_id}
GET   /internal/v1/nvt-projects
PATCH /internal/v1/nvt-projects/{nvt_project_id}
```

Transport status remains distinct from item outcome:

```text
201  first committed BusinessOperation
200  exact replay or READ
400/422 malformed structural request
401/403 trust or authority denial
404 tenant-safe absent resource
409 version, idempotency, or protected-state conflict
503 retryable OA or persistence dependency failure
```

A syntactically valid batch that commits some items and rejects others remains
a successful transport response with `PARTIALLY_APPLIED` domain status.

## 14. Contract and Evidence Deliverables

P8.11 SHALL add versioned schemas and examples for at least:

```text
nvt_project_create request / result
nvt_project_get / list request and result
nvt_project_update request / result
oa_employee_batch_resolve request / result
project_membership_add_many intake / admitted request / result
project_membership_batch_item_result
project_membership_batch_error
nsl_project_batch_write_artifact_admission
```

Positive and negative examples SHALL cover:

```text
NVT create/get/list/update success
NVT duplicate code, stale version, and active-Mother deactivation denial
same-tenant multi-member success
mixed valid, duplicate, absent, inactive, and name-mismatch candidates
all candidates rejected before approval
already-active no-op and removed-member reactivation
role conflict
cross-tenant non-enumerating resolution
requester revocation after approval
target revocation after resolution
exact replay and conflicting replay
single ADD versus ADD_MANY concurrency
OA unavailable and database rollback
unknown commit reconciliation
```

## 15. Persistence and Migration Rules

1. NVTProject operations reuse `eos_nvt_project`.
2. Batch membership reuses `eos_project_member`.
3. No new EOS table is authorized by CA05.
4. No OA database table is added solely for batch resolution.
5. A migration is added only if implementation finds a source-backed missing
   constraint or index that cannot be satisfied by the current schema.
6. Such a migration requires a short design amendment before implementation.
7. No cross-database foreign key or direct database read is allowed.
8. Historical P8 migrations and evidence remain immutable.

## 16. Authorized Implementation Sequence

The P8.11 sequence is:

| Slice | Scope |
| --- | --- |
| `P8-S104` | NVTProject governed repository/service gap closure |
| `P8-S105` | NVTProject protected API, authorization, and contracts |
| `P8-S106` | NVTProject NSL READ/WRITE artifacts and AE admission |
| `P8-S107` | OA employee batch-resolution boundary |
| `P8-S108` | Batch membership intake, canonicalization, and approval projection |
| `P8-S109` | EOS ADD_MANY transaction and partial item outcomes |
| `P8-S110` | NSL collection-valued ADD_MANY controlled WRITE |
| `P8-S111` | IA natural-language multi-member orchestration and result UX |
| `P8-S112` | Actual PostgreSQL, live generation, and Playwright protected acceptance |
| `P8-S113` | Repository Full Gate, zero residue, Final As-Built v1.2 closure |

Required gates:

```text
after P8-S107  Checkpoint Gate
after P8-S111  Checkpoint Gate
P8-S109        focused EOS/OA PostgreSQL concurrency smoke
P8-S112        actual OA/AE/WC/EOS PostgreSQL protected smoke
P8-S112        live generation for natural-language NVT/member journeys
P8-S112        authenticated Playwright demonstration journey
P8-S113        Repository Full Gate and zero-residue verification
```

Embedding and reranking providers are not required by P8.11. The live
generation provider is required only for the final natural-language journey.

## 17. Acceptance Invariants

P8.11 cannot close unless all of the following are true:

1. NVTProject CREATE/GET/LIST/UPDATE are tenant-scoped and current-authority
   protected.
2. NVT identity and code remain immutable after creation.
3. NVT UPDATE is optimistic and cannot inactivate an NVT with an active Mother
   Project.
4. `PROJECT.MEMBERSHIP.ADD_MANY` is one canonical business operation.
5. Existing single ADD/REMOVE/LIST identities and behavior remain compatible.
6. User employee input is resolved by OA; model output is never authority.
7. Cross-tenant candidates cannot be enumerated.
8. Names are confirmation hints, never identity keys.
9. One approval binds one exact canonical member set.
10. One NSL execution contains exactly one WRITE and no WRITE in FOREACH.
11. Invalid candidates do not block valid candidates after successful
    authoritative resolution.
12. Infrastructure, trust, and unknown-commit failures never masquerade as
    partial success.
13. Exact replay causes no additional membership mutation.
14. Concurrent single and batch ADD cannot create duplicate relationships.
15. Item outcomes and aggregate counts are deterministic and verified.
16. No new persistence table is introduced without a controlled amendment.
17. Actual PostgreSQL and authenticated browser acceptance pass with zero
    residue.
18. Repository statement coverage remains at least 96% and branch coverage at
    least 94%.

## 18. Closure Decision

```text
P8 v1.0 and v1.1 baselines remain immutable
P8-CA05 design closure is approved
P8.11 implementation entry is authorized
P8-S104 is the next implementation Slice
Demo Release Candidate refresh is held until P8-S113
P8 Final As-Built v1.2 is required for P8.11 closure
```

P9 entry authorization recorded by P8 v1.1 remains historically valid. The
current execution priority is the additive P8.11 demonstration closure. Any
change to batch atomicity, partial-outcome semantics, identity authority,
NVT status transitions, role cardinality, or NSL single-WRITE safety requires
another controlled design amendment before implementation.
