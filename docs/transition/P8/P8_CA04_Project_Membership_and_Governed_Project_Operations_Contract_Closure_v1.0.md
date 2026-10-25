# P8-CA04 Project Membership and Governed Project Operations Contract Closure v1.0

**Status:** DESIGN CLOSURE / P8.10 IMPLEMENTATION ENTRY AUTHORIZED

**Predecessor:** P8-S93 FINAL / P8 v1.0 AS-BUILT FROZEN

**Target Exit:** P8 FINAL AS-BUILT v1.1 / DEMO RELEASE ENTRY / P9 ENTRY RE-AUTHORIZED

**Date:** 2026-10-25

## 1. Purpose

P8-S93 closed a valid Controlled WRITE, approval, delegation, and Enterprise
OS baseline. A post-closure source audit identified one material business gap:
EOS persists `NVTProject` and `Project`, but it does not persist the people who
participate in a Project. Without an authoritative Project membership model,
the Platform cannot safely support:

```text
Project registration
Project lookup and list
Project member addition and removal
Project-scoped authorization
Project-scoped Voucher creation and lookup
natural-language Project operations through IA and NSL
```

This controlled amendment closes that gap before the P8 demonstration release.
It also establishes the naming convention that new NSL Skill, Tool, business
operation, and API contract identifiers SHALL follow from this point forward.

This document does not rewrite the P8-S93 baseline. It authorizes an additive
P8.10 implementation sequence and a later P8 Final As-Built v1.1 closure.

## 2. Source-Backed Finding

The current EOS source contains:

```text
eos_nvt_project
eos_project
SqlAlchemyEosProjectRepository.create_nvt_project()
SqlAlchemyEosProjectRepository.create_project()
SqlAlchemyEosProjectRepository.get_project()
SqlAlchemyEosProjectRepository.list_projects_for_nvt()
SqlAlchemyEosProjectRepository.resolve_nvt_project()
```

The current source does not contain:

```text
eos_project_member or equivalent table
ProjectMembership aggregate or repository
Project membership API
Project membership NSL Skill/Tool
Project membership authorization filter
Project-scoped Voucher query authorization
```

The current EOS OpenAPI exposes Voucher WRITE/verification, business-operation
lookup, and organization approver resolution. It does not expose governed
Project administration APIs.

The P8 v1.0 Project requirements define NVTProject separation, the three-level
Project hierarchy, stable Project identity, and NVT aggregation. They do not
define Project membership. CA04 is therefore an additive requirement closure,
not a correction to an implemented P8 v1.0 requirement.

## 3. Amendment Boundary

### 3.1 In scope

```text
EOS-owned Project membership persistence
Project membership lifecycle and tenant isolation
OA-backed actor and authority checks
governed Project and membership READ/WRITE APIs
NSL Skills and Tools for Project operations
IA natural-language Project operation admission
Project membership enforcement for Voucher operations
authoritative Project and Voucher lookup
P8 demonstration bootstrap and protected acceptance
NSL and API naming convention for all new contracts
```

### 3.2 Out of scope

```text
skill-pack hierarchy and distribution format
portfolio optimization
resource scheduling
timesheets and labor allocation
project profitability and NVT economics
bulk membership import
dynamic/custom Project role definitions
external directory synchronization
cross-tenant Project sharing
physical deletion of Project or membership history
retroactive rewrite of P8-S93 evidence
bulk rename of historical NSL Skills, Tools, or persisted executions
```

Skill packs remain the intended future organization mechanism. P8.10 SHALL use
a small flat Project operations source set and SHALL NOT invent a temporary
pack format that would later become another compatibility obligation.

## 4. Canonical NSL and Operation Naming

### 4.1 Required form

Every new business-facing identifier introduced by P8.10 SHALL use:

```text
<DOMAIN>.<BUSINESS_OBJECT>.<ACTION>
```

The canonical lexical rules are:

```text
DOMAIN          = uppercase ASCII snake case
BUSINESS_OBJECT = uppercase ASCII snake case
ACTION          = uppercase ASCII snake case, normally one imperative verb
separator       = exactly one period
segment count   = exactly three
```

Examples:

```text
PROJECT.PROJECT.CREATE
PROJECT.PROJECT.GET
PROJECT.PROJECT.LIST
PROJECT.PROJECT.DEACTIVATE
PROJECT.MEMBERSHIP.ADD
PROJECT.MEMBERSHIP.REMOVE
PROJECT.MEMBERSHIP.LIST
FINANCE.VOUCHER_DRAFT.CREATE
FINANCE.VOUCHER_DRAFT.GET
FINANCE.VOUCHER_DRAFT.LIST
```

The repeated `PROJECT.PROJECT` form is intentional. The first segment is the
business domain and the second segment is the business object. Omitting either
segment makes automated cataloging ambiguous once skill packs contain several
objects in one domain.

### 4.2 Naming semantics

The identifier describes business semantics, not the implementing service,
transport, database table, or Python class.

Allowed:

```text
PROJECT.MEMBERSHIP.ADD
FINANCE.VOUCHER_DRAFT.GET
```

Not allowed for new contracts:

```text
EOS.CREATE_PROJECT
PROJECT.ADD_MEMBER
CREATE_PROJECT_MEMBER
POST_PROJECT_MEMBERSHIP
PROJECT.MEMBERSHIP.API_V1
```

Actions SHALL remain stable and unsurprising:

```text
CREATE      create one new business object
GET         read one known business object
LIST        read a filtered collection
ADD         establish a relationship
REMOVE      end a relationship without physical deletion
DEACTIVATE  end normal use of a business object
VERIFY      perform authoritative post-operation verification
RESOLVE     convert candidates into one canonical reference
```

`DELETE` SHALL NOT be used when the domain operation preserves audit history.
Project membership uses `REMOVE`; Project lifecycle uses `DEACTIVATE`.

### 4.3 Scope of application

The three-segment form applies to new:

```text
NSL skill_id
NSL tool_id
Platform capability and operation identifiers
RuntimePolicy operation keys
business operation type identifiers
audit and evidence operation identifiers
OpenAPI canonical operation annotations
```

File names SHALL be lowercase snake case derived from the identifier:

```text
PROJECT.PROJECT.CREATE     -> project_project_create.ns
PROJECT.MEMBERSHIP.ADD     -> project_membership_add.ns
FINANCE.VOUCHER_DRAFT.GET  -> finance_voucher_draft_get.ns
```

Skill and Tool registries are distinct namespaces. A Skill and its terminal
WRITE Tool MAY share the same canonical business identifier, but each retains
its own exact version and semantic hash.

### 4.4 Versioning rule

Changing any segment of a Skill or Tool identifier is a contract identity
change. It is not a formatting-only refactor.

Each canonical contract SHALL be admitted by:

```text
canonical identifier
exact semantic version
exact schema/contract version
exact semantic hash
exact artifact digest
```

Renaming an admitted `.ns` declaration requires a new Skill version and a new
semantic hash. Existing executions, approvals, checkpoints, idempotency
evidence, and audit records SHALL retain the identifier originally admitted.

## 5. Legacy Identifier Compatibility

P8 v1.0 and the admitted NSL v0.2 examples contain two-segment identifiers in
the older `DOMAIN.ACTION_OBJECT` or `DOMAIN.ACTION` shape. Examples include:

```text
FINANCE.CREATE_VOUCHER_DRAFT
FINANCE.GET_VOUCHER_DRAFT
FINANCE.RESOLVE_VOUCHER_DRAFT_COMMAND
PROJECT.GET_PROJECT
ACCOUNT.GET_ACCOUNT
```

They remain historical contract identities and SHALL NOT be rewritten in
place. New P8.10 source SHALL use the canonical three-segment shape.

The initial compatibility map is:

| Legacy identifier | Canonical identifier | Treatment |
| --- | --- | --- |
| `FINANCE.CREATE_VOUCHER_DRAFT` | `FINANCE.VOUCHER_DRAFT.CREATE` | versioned alias for new admission; historical lineage unchanged |
| `FINANCE.GET_VOUCHER_DRAFT` | `FINANCE.VOUCHER_DRAFT.GET` | versioned alias for new admission; historical lineage unchanged |
| `FINANCE.RESOLVE_VOUCHER_DRAFT_COMMAND` | `FINANCE.VOUCHER_DRAFT.RESOLVE_COMMAND` | versioned alias for new admission |
| `PROJECT.GET_PROJECT` | `PROJECT.PROJECT.GET` | versioned alias for new admission |

The alias boundary SHALL obey all of the following:

1. Alias resolution occurs before a new execution computes semantic,
   idempotency, approval, or WRITE lineage.
2. A new execution records both the requested identifier and the canonical
   identifier when they differ.
3. All hashes and policy decisions for that new execution use the canonical
   identifier consistently.
4. Retry and resume use the already admitted canonical identity; they do not
   resolve the alias again.
5. Historical executions continue to replay their exact persisted legacy
   identity and version.
6. Submitting the same semantic command once through the legacy alias and once
   through the canonical name SHALL NOT bypass idempotency.
7. Unknown, ambiguous, chained, or cyclic aliases fail closed.

The complete historical catalog migration is not a P8.10 goal. CA04 only
defines the rule and the aliases needed by the Project/Voucher demonstration
journey.

## 6. API Naming Alignment

HTTP resources remain resource-oriented. Dotted NSL identifiers SHALL NOT be
copied into URL paths.

Recommended routes:

```text
POST   /internal/v1/projects
GET    /internal/v1/projects/{project_id}
GET    /internal/v1/projects
POST   /internal/v1/projects/{project_id}/memberships
GET    /internal/v1/projects/{project_id}/memberships
DELETE /internal/v1/projects/{project_id}/memberships/{project_membership_id}
```

The `DELETE` HTTP method above invokes the business action
`PROJECT.MEMBERSHIP.REMOVE`; it SHALL update lifecycle state and SHALL NOT
physically delete the row.

OpenAPI `operationId` remains code-generator friendly:

```text
createEosProject
getEosProject
listEosProjects
addEosProjectMembership
listEosProjectMemberships
removeEosProjectMembership
```

Every operation SHALL also publish the canonical business identifier through
the repository's canonical OpenAPI extension, using
`x-nex-canonical-operation` when the implementation is added. Request,
response, audit, and evidence payloads SHALL use the same identifier.

API paths, Python method names, table names, OpenAPI `operationId`, and NSL
identifiers therefore remain related but are not forced into one syntax.

## 7. Project Membership Ownership

EOS SHALL own Project membership because it owns the Project business object
and Project-scoped business transactions.

OA SHALL continue to own:

```text
tenant identity
employee and service principal identity
credential and session state
role/group authority
current subject lifecycle
authorization decisions
```

EOS SHALL own:

```text
Project identity and hierarchy
Project membership business relationship
Project role within that relationship
membership effective period and lifecycle
Project-scoped business admission
```

`subject_id` in EOS is an opaque, stable OA reference. EOS SHALL NOT create a
cross-database foreign key to OA, copy employee credentials, or treat a display
employee number as identity authority.

Project membership is not an OA permission by itself. A protected action is
admitted only when both are true:

```text
current OA authority permits the action
current EOS Project membership permits the Project scope
```

Permissions from several memberships SHALL NOT be unioned to create authority
outside the explicitly selected Project.

## 8. Persistence Contract

### 8.1 New table

P8.10 SHALL add one owner-local EOS table:

```text
eos_project_member
```

Minimum columns:

```text
tenant_id                    varchar(128)  not null
project_membership_id        uuid          not null
project_id                   uuid          not null
subject_id                   varchar(128)  not null
member_role                  varchar(32)   not null
status                       varchar(16)   not null
valid_from                   timestamptz   not null
valid_to                     timestamptz   null
version                      integer       not null
created_by_subject_id        varchar(128)  not null
removed_by_subject_id        varchar(128)  null
created_at                   timestamptz   not null
updated_at                   timestamptz   not null
```

Keys and constraints:

```text
primary key        = (tenant_id, project_membership_id)
project foreign key = (tenant_id, project_id) -> eos_project
unique relationship = (tenant_id, project_id, subject_id)
status             = ACTIVE | REMOVED
version            >= 1
ACTIVE             => valid_to is null and removed_by_subject_id is null
REMOVED            => valid_to and removed_by_subject_id are not null
```

Required indexes:

```text
(tenant_id, project_id, status, member_role)
(tenant_id, subject_id, status, project_id)
```

The table name is intentionally short enough for PostgreSQL constraint and
index naming. Existing `eos_project` and `eos_nvt_project` remain unchanged.

### 8.2 Initial role codes

The minimum fixed P8.10 role set is:

```text
OWNER
MANAGER
MEMBER
VIEWER
```

Custom roles and role inheritance are deferred. Role changes require a later
explicit `PROJECT.MEMBERSHIP.CHANGE_ROLE` contract and SHALL NOT be smuggled
into ADD or REMOVE.

### 8.3 Lifecycle

```text
ABSENT -> ACTIVE  through PROJECT.MEMBERSHIP.ADD
ACTIVE -> REMOVED through PROJECT.MEMBERSHIP.REMOVE
REMOVED -> ACTIVE through an idempotent, versioned reactivation
```

ADD with the same active subject, Project, and role returns the existing
membership. ADD with a conflicting role fails closed until an explicit role
change contract exists. Repeated REMOVE returns the same terminal membership
without creating another business mutation.

Physical deletion is prohibited. The existing EOS BusinessOperation and
outbox lineage SHALL carry mutation audit and exactly-once publication; CA04
does not require a second membership event table.

### 8.4 Existing Project bootstrap

The additive migration SHALL NOT fabricate owners for existing Projects.
Existing Projects become governed only after an authorized bootstrap assigns
an initial OWNER. Until then, governed Project or Voucher operations that
require membership fail closed with a typed `PROJECT_MEMBERSHIP_REQUIRED`
outcome.

New governed Project creation SHALL accept one `initial_owner_subject_id` and
atomically create the Project plus its initial OWNER membership. A Project
without an active OWNER SHALL not be created through the public governed API.

The last active OWNER cannot be removed while the Project is active.

## 9. Governed Project Operations

The initial canonical operation catalog is:

| Canonical identifier | Mode | Required result |
| --- | --- | --- |
| `PROJECT.PROJECT.CREATE` | WRITE | Project and initial OWNER are committed atomically |
| `PROJECT.PROJECT.GET` | READ | one tenant- and authority-filtered Project |
| `PROJECT.PROJECT.LIST` | READ | bounded Project collection filtered by membership/authority |
| `PROJECT.PROJECT.DEACTIVATE` | WRITE | Project becomes inactive; no physical deletion |
| `PROJECT.MEMBERSHIP.ADD` | WRITE | one active relationship or stable idempotent replay |
| `PROJECT.MEMBERSHIP.REMOVE` | WRITE | relationship becomes REMOVED or stable terminal replay |
| `PROJECT.MEMBERSHIP.LIST` | READ | bounded membership list for one authorized Project |

All WRITE operations SHALL reuse the P8 controlled-WRITE foundation:

```text
candidate admission
RuntimePolicy
current OA authorization
NSL_WRITE approval when policy requires it
idempotency evidence
WRITE_REQUESTED evidence
EOS BusinessOperation
commit outcome
reconciliation when outcome is unknown
post-WRITE verification
durable result and audit lineage
```

Policy, not the `.ns` source, decides whether a particular authorized Project
mutation requires human approval. The Skill SHALL never bypass RuntimePolicy.

## 10. Authorization Matrix

Minimum P8.10 policy:

| Operation | OA authority | EOS Project condition |
| --- | --- | --- |
| Project create | tenant Project administrator | no existing membership; initial OWNER required |
| Project get/list | Project read authority | active membership, or explicit tenant administrator override |
| Project deactivate | Project administration authority | active OWNER |
| Membership add | membership management authority | active OWNER or MANAGER |
| Membership remove | membership management authority | active OWNER or MANAGER; last OWNER protected |
| Voucher create | Voucher create authority | active Project membership with admitted role |
| Voucher get/list | Voucher read authority | active Project membership with admitted role, or explicit finance auditor override |

The exact OA scope strings SHALL be versioned contract values during
implementation. They SHALL not be inferred from a display role label.

Every protected action rechecks current OA subject status, current authority,
Project status, and membership status. A previously admitted browser session,
plan, approval, or Skill does not freeze those decisions indefinitely.

## 11. NSL Source Contract

P8.10 SHALL initially create a flat Project operation source set in the NSL
repository. It SHALL not create a skill-pack manifest yet.

Recommended files:

```text
project_project_create.ns
project_project_get.ns
project_project_list.ns
project_project_deactivate.ns
project_membership_add.ns
project_membership_remove.ns
project_membership_list.ns
finance_voucher_draft_get.ns
finance_voucher_draft_list.ns
```

Each source SHALL:

1. declare only canonical three-segment Skill and Tool identifiers;
2. use stable `tenant_id`, `project_id`, `subject_id`, and membership IDs;
3. resolve human-facing Project codes before WRITE admission;
4. reject ambiguous Project or employee candidates;
5. emit no execution authority from model-generated text;
6. preserve exact semantic hash and Tool contract version;
7. separate READ from governed WRITE;
8. return typed no-access, not-found, inactive, and conflict outcomes;
9. avoid direct database access;
10. execute only through admitted Platform ports and EOS APIs.

New or changed NSL artifacts require native NSL tests, artifact admission,
semantic-hash evidence, Platform adapter regression, and exact source/wheel
identity evidence appropriate to the distribution mechanism.

## 12. IA Natural-Language Boundary

IA may accept requests such as:

```text
새 프로젝트 '신제품 출시'를 만들고 나를 책임자로 등록해줘.
PROJECT-A에 사번 10234 직원을 멤버로 추가해줘.
PROJECT-A의 현재 멤버를 보여줘.
PROJECT-A에서 사번 10234 직원을 제외해줘.
내가 참여 중인 프로젝트를 보여줘.
PROJECT-A 출장비 전표 초안을 만들어줘.
PROJECT-A의 최근 전표 초안을 조회해줘.
```

The generation provider produces an untrusted candidate intent and arguments.
Deterministic admission SHALL resolve:

```text
one canonical operation identifier
one tenant
one current OA subject
one ProjectRef
zero or one target subject, as required
one exact contract and Skill version
```

Ambiguous Project codes, employee references, roles, or destructive intent
require clarification. IA SHALL not guess an employee identity or Project.

Authoritative Project and Voucher lookup is a structured EOS READ. RAG/vector
retrieval SHALL NOT be used as the business source of truth for membership,
Project status, Voucher identity, or authorization.

## 13. Voucher Integration

P8.10 SHALL align the existing Voucher operations with canonical names for new
execution admission:

```text
FINANCE.VOUCHER_DRAFT.CREATE
FINANCE.VOUCHER_DRAFT.GET
FINANCE.VOUCHER_DRAFT.LIST
```

The existing P8 v1.0 identifiers remain valid for their frozen contracts and
historical execution lineage.

Before a new Voucher operation is admitted, the Platform SHALL verify:

```text
Project exists and is ACTIVE
requester has current OA authority
requester has current admitted Project membership or explicit auditor override
ProjectRef belongs to the same tenant
query filters cannot escape the admitted Project/tenant scope
```

`LIST` SHALL be bounded, paginated, deterministically ordered, and filtered at
the authoritative EOS query boundary. Filtering only in IA or AE is forbidden.

## 14. Contract and Schema Deliverables

P8.10 implementation SHALL add versioned contracts for at least:

```text
project_create_request / result
project_get / list request and result
project_deactivate_request / result
project_membership_add_request / result
project_membership_remove_request / result
project_membership_list request / result
project_operation_error
canonical_operation_alias
voucher_draft_list request / result
```

Positive and negative examples SHALL cover:

```text
same-tenant success
cross-tenant denial
inactive OA subject
missing OA authority
missing/removed membership
duplicate ADD replay
duplicate REMOVE replay
conflicting role ADD
last OWNER removal denial
inactive Project
ambiguous Project code
ambiguous employee reference
legacy alias and canonical idempotency equivalence
unknown/cyclic alias rejection
```

OpenAPI, JSON Schema, NSL Tool contracts, RuntimePolicy keys, and audit event
names SHALL use the same canonical operation identity.

## 15. Migration and Compatibility Rules

1. Add one EOS migration after `2513_eos_voucher_attachment_lineage`.
2. Keep every P8-S93 migration immutable.
3. Do not add an OA-side Project member table.
4. Do not create cross-database foreign keys.
5. Preserve existing direct repository setup used by historical P8 fixtures.
6. Route all new public/internal governed operations through the new service
   layer and authorization boundary.
7. Do not mutate historical `tool_id`, `skill_id`, semantic hash, approval, or
   BusinessOperation rows.
8. New aliases are admitted registry data, not ad hoc string replacement.
9. SQLite regression may test deterministic behavior, but concurrency,
   constraints, migration, and protected authority require PostgreSQL evidence.
10. Table, constraint, and index names SHALL remain below PostgreSQL's
    identifier limit and follow the existing EOS naming style.

## 16. Implementation Sequence

The authorized P8.10 sequence is:

| Slice | Scope |
| --- | --- |
| `P8-S94` | EOS Project membership migration and persistence foundation |
| `P8-S95` | Membership lifecycle, idempotency, and repository hardening |
| `P8-S96` | Governed Project service/API and OA-backed authorization |
| `P8-S97` | Canonical operation alias registry and API naming enforcement |
| `P8-S98` | Canonical Project NSL READ Skills/Tools |
| `P8-S99` | Canonical Project NSL governed WRITE Skills/Tools |
| `P8-S100` | IA Project operations and clarification/admission integration |
| `P8-S101` | Membership-filtered Voucher create/get/list integration |
| `P8-S102` | Demo bootstrap, PostgreSQL/provider/Playwright protected acceptance |
| `P8-S103` | P8 Final As-Built v1.1 and Demo Release/P9 handoff |

Recommended gates:

```text
after P8-S97   Checkpoint Gate
after P8-S101  Checkpoint Gate
P8-S102        actual EOS/OA/AE/WC PostgreSQL protected smoke
P8-S102        live generation provider for natural-language journeys
P8-S102        authenticated Playwright demonstration journey
P8-S103        Repository Full Gate and zero-residue closure
```

Embedding and reranking providers are not required for authoritative Project
or Voucher queries. The live generation provider is required only for the IA
natural-language acceptance journey.

## 17. Acceptance Invariants

P8.10 cannot close unless all of the following are true:

1. Every new Skill and Tool uses exactly three canonical identifier segments.
2. Existing P8 v1.0 execution and evidence lineage remains unchanged.
3. Legacy aliases and canonical identifiers cannot create duplicate business
   mutation or bypass approval/idempotency.
4. Project creation and initial OWNER membership commit atomically.
5. No active Project can lose its last active OWNER.
6. Membership removal preserves durable audit and business lineage.
7. Cross-tenant Project and membership access fails closed.
8. Current OA revocation is honored before each protected action.
9. Project membership never substitutes for OA authority.
10. OA authority never substitutes for required Project membership.
11. Voucher CREATE/GET/LIST is Project- and tenant-filtered at EOS.
12. IA ambiguity never reaches governed WRITE.
13. Retry, restart, and replay produce at most one semantic mutation.
14. Actual PostgreSQL migration, constraint, and concurrency evidence passes.
15. The authenticated demonstration journey works from clean bootstrap through
    Project membership, natural-language Voucher creation, and Voucher lookup.
16. Repository statement coverage remains at least 96% and branch coverage at
    least 94%.

## 18. Closure Decision

```text
P8-S93 v1.0 baseline remains frozen
P8-CA04 design closure is approved
P8.10 implementation entry is authorized
P9 implementation entry is held until P8-S103
P8 Final As-Built v1.1 is required before Demo Release tagging
```

P8-S94 may begin only from this contract closure or an explicitly versioned
successor. Any change to ownership, canonical identifier shape, last-OWNER
protection, deletion semantics, or Voucher membership enforcement is a design
decision and requires a new controlled amendment before implementation.
