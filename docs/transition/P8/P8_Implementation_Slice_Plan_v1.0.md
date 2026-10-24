# P8 Implementation Slice Plan v1.0

**Phase:** P8 — Controlled WRITE / Approval / Delegation / Enterprise OS  
**Status:** PRE-IMPLEMENTATION EXECUTION PLAN  
**Input Baselines:**  
- `P8_Pre_Architecture_Decision_Controlled_WRITE_Approval_and_Enterprise_OS_v1.0.md`
- `P8_Source_Audit_Controlled_WRITE_Approval_and_Enterprise_OS_v1.0.md`
- `P8_CA01_Controlled_WRITE_Approval_Delegation_EOS_Contract_Closure_v1.0.md`
- `P8_CA01A_NVT_Project_Hierarchy_and_Voucher_Attachment_Amendment_v1.0.md`
- `P8_Controlled_WRITE_Approval_Delegation_and_Enterprise_OS_SRS_v1.0.md`

**Platform Repository:** `nurigitdev/2607_nex_platform`  
**Platform Entry Commit:** `ce1fb8cb2373ab8024bd1ee96c5c641a30368c3a`  
**NSL Repository:** `nurigitdev/2608_nsl`  
**Certified NSL v0.2 Commit:** `5cd81e18ffbedeee83605cd2e6a6cbcab54c1fb6`  
**Certified NSL v0.2 Tree:** `71dbea8cca563867b12acd07462a2dcd42d9a8ac`  
**Platform Quality Gate:** Statement Coverage ≥ 96%, Branch Coverage ≥ 94%  
**NSL Native Quality Gate:** Statement Coverage ≥ 99%, Branch Coverage ≥ 98%  
**EOS Databases:** `nex_eos_dev`, `nex_eos_test`  
**Date:** 2026-10-21

---

# 1. Purpose

This plan converts the P8 SRS into small implementation / verification /
commit units.

P8 SHALL not be implemented as one large branch-level feature.

Each Slice is expected to follow:

```text
inspect current source
→ refactor first if needed
→ implement one bounded semantic change
→ unit / contract / negative tests
→ regression
→ protected smoke where required
→ commit
→ synchronize
```

A Slice is complete only when its own exit criteria pass.

---

# 2. Core Execution Principle

P8 implementation SHALL preserve:

```text
LLM Candidate
!=
Execution Authority

Human UI Action
!=
Business Mutation Authority

Technical Retry
!=
Business WRITE Retry

NSL WRITE Approval
!=
BUSINESS_FORMAL Approval

WC Human Task
!=
EOS Business Approval SoR
```

The final WRITE path remains:

```text
Plan
→ deterministic validation
→ NSL
→ exact Approval
→ WriteGuard
→ Idempotency
→ WRITE_REQUESTED
→ current EOS authorization
→ EOS mutation
→ CommitState
→ Verification
```

---

# 3. Implementation Rules

## 3.1 Refactor First

Before adding a behavior, inspect whether the target code requires a structural
refactor.

Refactor SHALL precede behavior changes when:

```text
duplicate code would otherwise be created
P7 source is WorkResult-specific but P8 needs a generic core
service boundary would be violated
testability requires dependency injection
state transition logic is duplicated
```

Behavior-preserving refactor and new behavior SHOULD be separate commits when
practical.

---

## 3.2 Test Before Commit

Every source-changing Slice SHALL run:

```text
focused unit tests
focused integration tests
relevant regression
coverage gate or bounded coverage check
```

DB-related Slices SHALL also run:

```text
fresh test DB / reset
migration
positive path
negative path
residue check
```

Web UI Slices SHALL use Playwright.

---

## 3.3 No Cross-Service DB Access

Implementation SHALL not solve integration by reading/writing another service's
tables directly.

Use:

```text
service API
versioned event
stable ref
```

only.

---

## 3.4 Contract First

A new cross-service payload SHALL be added in this order:

```text
schema
→ positive example
→ negative examples
→ contract validation
→ producer
→ consumer
→ integration smoke
```

---

## 3.5 Commit Discipline

Recommended commit shape:

```text
one Slice
→ one semantic topic
→ regression PASS
→ commit
→ remote sync
```

Do not batch unrelated P8 slices into one commit merely for speed.

---

# 4. Phase Structure

P8 is divided into:

```text
P8.1   NSL v0.2 Release Admission & Integration Acceptance
P8.2   NeX-EOS Foundation
P8.2A  WC Delegation Guard
P8.3   Human Approval Foundation
P8.4   NSL Approval Suspend / Resume Integration
P8.5   Governed WRITE → EOS
P8.6   Golden A Voucher Draft
P8.7   BUSINESS_FORMAL / Multi-stage Approval
P8.8   Reliability / Reconciliation Closure
P8.9   Full Gate / Final As-Built Freeze
```

`P8.2` and `P8.2A` may proceed in parallel only after P8.1 admission contracts
are stable.

---

# 5. P8.1 — NSL v0.2 Release Admission & Integration Acceptance

Goal:

```text
certified NSL v0.2 wheel
→ exact Platform admission
→ explicit NSL_V02 profile
→ compatibility smoke
```

No EOS business mutation is allowed in P8.1.

---

## P8-S01 — Actual NSL v0.2 Wheel Identity Closure

### Objective

Verify the actual released wheel, not only the repository label.

### Required evidence

```text
wheel filename
distribution
package version
wheel SHA256
source revision
source tree
Requires-Python
dependencies
public API inventory
```

### Actions

1. Locate the released v0.2 wheel.
2. Run existing wheel inspection.
3. Compare wheel METADATA with certified source.
4. Record source commit/tree and wheel digest.
5. Confirm package version is admitted as v0.2.

### Blocking rule

If actual wheel says:

```text
version = 0.1.0
```

P8 Platform admission SHALL stop.

A corrected NSL release SHALL be produced first.

### Tests

```text
RA-01 distribution exact
RA-02 version exact
RA-03 source revision exact
RA-04 source tree exact
RA-05 SHA256 exact
```

### Exit

```text
immutable NSL v0.2 release identity = CLOSED
```

---

## P8-S02 — NSL v0.2 Wheel Lock Contract

### Objective

Create the Platform-side immutable lock for NSL v0.2.

### Candidate source targets

```text
deployment/locks/
services/_shared/nex_runtime/nsl_package_admission.py
scripts/deployment/admit_nsl_wheel.py
tests/test_nex_runtime_nsl_package_admission.py
```

### Implementation

Add a versioned lock containing:

```text
repository
source_revision
source_tree
distribution
package_version
wheel_filename
wheel_sha256
requires_python
requirements
public_api_symbols
Platform lock digest
```

### Tests

```text
wrong source revision
wrong tree
wrong filename
wrong digest
wrong package version
wrong dependency
missing public API
tampered RECORD
```

### Exit

Exact wheel admission record is reproducible.

---

## P8-S03 — `NSL_V02_IN_PROCESS` Backend Profile

### Objective

Introduce an explicit v0.2 runtime profile.

### Candidate source targets

```text
services/nex-ae-api/nex_ae_api/nsl_backend_profiles.py
services/nex-ae-api/nex_ae_api/nsl_step_executions.py
tests/test_ae_p6_s3_nsl_step_execution.py
tests/test_ae_p6_s5_nsl_read_backend.py
```

### Required behavior

Retain:

```text
NSL_V01_IN_PROCESS
NSL_V01_PROCESS_ISOLATED
```

Add:

```text
NSL_V02_IN_PROCESS
```

### Rules

```text
NSL 0.2 WRITE
→ v0.2 only

v0.1 historical READ
→ remains compatible
```

### Negative tests

```text
WRITE + V01 profile rejected
unknown profile rejected
profile mismatch rejected
```

---

## P8-S04 — Installed v0.2 Package Readiness

### Objective

Verify the installed package is the exact admitted wheel.

### Candidate source targets

```text
services/_shared/nex_runtime/nsl_package_admission.py
AE readiness integration
```

### Checks

```text
installed package version
wheel origin
wheel digest
public API import location
Platform dependency lock
release admission hash
```

### Exit

AE readiness fails closed on wrong/stale NSL installation.

---

## P8-S05 — v0.2 Public API Adapter Foundation

### Objective

Create a narrow AE integration module that imports only admitted `nsl.api`
public symbols needed by P8.

### Required surface

```text
ApprovalRequest
ApprovalEvidence
ApprovalSuspensionCoordinator
ApprovalResumeCoordinator
CheckpointPort
ResumeCheckpointPort
IdempotencyCoordinator
WriteExecutionPort
PostWriteVerificationPort
RuntimePreflightValidator
```

### Constraint

No broad:

```text
from nsl.internal...
```

private dependency.

### Tests

Architecture tests SHALL fail if the P8 adapter imports prohibited NSL private
modules.

---

## P8-S06 — NSL v0.2 Compatibility Smoke

### Objective

Prove admission does not break existing P6 behavior.

### Acceptance

```text
v0.1 READ regression PASS
v0.2 READ smoke PASS
v0.2 WRITE mock controlled-prefix PASS
zero EOS mutation
```

### Gate

**P8.1 CLOSED** only after S01-S06 PASS.

---

# 6. P8.2 — NeX-EOS Foundation

Goal:

```text
new service
+ database
+ minimal business domain
+ Golden-A-ready command foundation
```

No full ERP implementation.

---

## P8-S07 — NeX-EOS Service Skeleton

### Objective

Introduce service package without domain behavior.

### Candidate structure

```text
services/nex-eos/
  nex_eos/
    app.py
    config.py
    health.py
    dependencies.py

database/nex-eos/
contracts/openapi/nex-eos.openapi.yaml
```

### Required endpoints

```text
health
ready
version/build
```

### Tests

```text
startup
invalid config fail closed
health
readiness
build identity
service trust baseline
```

---

## P8-S08 — EOS DB Bootstrap

### Objective

Create service-owned DB migration baseline.

### Databases

```text
nex_eos_dev
nex_eos_test
```

### Required

```text
schema_migrations
service-owned role/pool conventions
transaction helper
test reset helper
```

### Tests

```text
fresh migration
re-run migration
rollback/error behavior
test DB reset
```

---

## P8-S09 — EOS BusinessOperation / Idempotency / Outbox Core

### Objective

Implement cross-domain transaction infrastructure before Voucher logic.

### Logical tables

```text
eos_business_operation
eos_idempotency
eos_outbox
```

### Required semantics

```text
BusinessOperationId stable
same key + same payload → reuse
same key + different payload → conflict
business commit + outbox atomic
```

### Tests

Boundary and concurrency tests are required.

---

## P8-S10 — EOS Organization Core

### Objective

Implement minimal business organization SoR.

### Logical tables

```text
eos_org_unit
eos_position
eos_position_assignment
```

### Types

```text
PART
TEAM
GROUP
COMPANY

PART_LEAD
TEAM_LEAD
GROUP_LEAD
CEO
CHAIRMAN
```

### Tests

```text
effective assignment
inactive assignment
duplicate active position assignment policy
cross-tenant ref
OA principal-ref shape
```

---

## P8-S11 — NVTProject Foundation

### Objective

Implement `NVTProject` as a separate business object.

### Logical fields

```text
nvt_project_id
nvt_project_code
name
status
version
created_at
updated_at
```

### Tests

```text
unique code
tenant isolation
active/inactive state
versioning
```

---

## P8-S12 — Project Hierarchy Foundation

### Objective

Implement ordinary Project hierarchy.

### Required semantics

```text
Mother:
  parent_project_id = NULL
  nvt_project_id != NULL

Child:
  parent_project_id != NULL
```

### Maximum depth

```text
3
```

### Tests

```text
depth 1/2/3 PASS
depth 4 DENY
self-parent DENY
cycle DENY
child under wrong tenant DENY
```

---

## P8-S13 — NVT Aggregation / Project Resolution Query

### Objective

Support:

```text
NVTProject
→ Mother Projects
→ all descendants
```

and descendant-to-NVT resolution.

### Implementation

Initial PostgreSQL recursive traversal is acceptable.

### Tests

```text
multiple Mothers
deepest level
empty NVT
wrong NVT isolation
bounded query
```

---

## P8-S14 — Account Minimum Model

### Objective

Implement exact Account stable refs for Golden A.

### Minimum

```text
account_id
account_code
name
category/type
status
effective period
version
```

### Tests

```text
active
inactive
expired
unknown
cross-tenant
```

---

## P8-S15 — VoucherDraft Aggregate Foundation

### Objective

Implement Draft aggregate and lines, without external WRITE API yet.

### Logical tables

```text
eos_voucher_draft
eos_voucher_draft_line
```

### Requirements

```text
DRAFT state
ProjectRef
currency
transaction_date
description
requester/source refs
balanced lines
version
```

### Tests

```text
valid balance
unbalanced DENY
zero lines DENY
invalid Project
invalid Account
Decimal boundary
```

---

## P8-S16 — Voucher Attachment Metadata / RustFS Reference Model

### Objective

Add attachment association model without implementing full document lifecycle.

### Logical table

```text
eos_voucher_draft_attachment
```

### Fields

```text
attachment_id
voucher_id
object_ref
display_name
media_type
size_bytes
content_sha256
evidence_ref
created_at
```

### Rules

Do not persist:

```text
RustFS credentials
presigned URL as stable identity
filesystem path
```

### Tests

```text
0 attachment
1 attachment
N attachments
cross-tenant object ref DENY
credential-like durable identity DENY
```

### Note

Actual RustFS upload/download may remain a later sub-slice if Golden A has no
attachment.

---

## P8-S17 — EOS Authorization Client

### Objective

Add fresh business-command OA authorization at EOS mutation boundary.

### Initial scope

```text
finance:voucher-draft:create
```

### Required checks

```text
service trust
on-behalf-of principal
active principal
business scope
tenant/project/org/resource scope
```

### Failure

```text
zero mutation
```

---

## P8-S18 — Voucher Draft Command Contract

### Objective

Freeze machine-readable:

```text
FINANCE.CREATE_VOUCHER_DRAFT
```

request/result.

### Contract first

Add:

```text
JSON Schema
positive example
negative examples
OpenAPI
contract tests
```

### Request binds

```text
BusinessOperationId
IdempotencyKey
PayloadHash
ProjectRef
AccountRef(s)
Money
NSL approval refs
trace
optional attachment refs
```

---

## P8-S19 — EOS Create Voucher Draft Service

### Objective

Implement command transaction.

### Atomic commit

```text
VoucherDraft
lines
attachment associations if supplied
BusinessOperation
Idempotency result
Outbox
```

### Required

Fresh OA authorization and PayloadHash verification happen before mutation.

---

## P8-S20 — EOS BusinessOperation / Reconciliation Query

### Objective

Implement authoritative query by BusinessOperationId.

### Output

```text
operation
payload_hash
commit_state
business_transaction_ref
voucher_ref
reconciliation_status
last_observed_at
```

### Tests

```text
committed
not committed
unknown
unknown operation
cross tenant
```

---

## P8-S21 — EOS Verification Read API

### Objective

Implement side-effect-free Voucher read suitable for NSL PostWriteVerification.

### Required

```text
VoucherRef
BusinessOperationId
stable business state
```

### Test

Assert DB mutation count remains zero during verification read.

---

## P8-S22 — EOS Foundation Protected PostgreSQL Gate

### Objective

Run a real EOS DB protected smoke across S07-S21.

### Evidence

```text
migration head
service build identity
test DB identity
transaction counts
outbox counts
zero residue
```

### Gate

**P8.2 CLOSED** when S07-S22 PASS.

---

# 7. P8.2A — WC Delegation Guard

This stream may proceed in parallel with P8.2 after P8.1.

---

## P8-S23 — Delegation Guard Contract Pack

### Objective

Add P8 transition contracts:

```text
DelegationPolicy
DelegationLineage
extended nested DelegationSpec
error examples
```

### Fixed initial policy

```text
max_depth       = 10
max_children    = 5
max_descendants = 50
cycle_detection = true
```

---

## P8-S24 — Delegation Lineage Persistence

### Objective

Add durable lineage.

### Logical relation

```text
wc_delegation_lineage
```

### Required fields

```text
work_item_id
root_work_item_id
parent_work_item_id
parent_claim_ref
parent_claim_generation
delegating_agent_ref
delegation_depth
policy_ref/hash
```

### Tests

Historical P7 WorkItems remain valid.

---

## P8-S25 — First-Level Depth / Root Admission

### Objective

For first Agent delegation:

```text
depth = 1
root = child WorkItem itself
parent_work_item_id = null
```

### Tests

Idempotent replay preserves same lineage.

---

## P8-S26 — Nested Delegation Parent Claim Authority

### Objective

Require current parent Claim for nested child creation.

### Verify

```text
ACTIVE
generation match
lease valid
assignment match
claimant match
parent AgentExecution match
```

### Negative

Stale/expired/reclaimed Claim creates zero child.

---

## P8-S27 — Hop Limit

### Objective

Reject prospective depth > 10.

### Important

Current depth-10 WorkItem remains executable.

### Error

```text
wc.delegation_hop_limit_exceeded
```

---

## P8-S28 — Direct Child Budget

### Objective

Enforce max direct children = 5.

### Concurrency

Protection must be transactional.

### Test

Concurrent attempts cannot create child #6.

---

## P8-S29 — Root Descendant Budget

### Objective

Enforce root total descendants <= 50.

### Test

Concurrent children across multiple parents cannot exceed root budget.

---

## P8-S30 — Claim-Time Cycle Detection

### Objective

Before Claim commit, reject candidate Agent present in ancestor delegating
Agent chain.

### Example

```text
A → B → C → A
```

final A denied.

### Result

```text
zero Claim
zero Assignment
zero AgentExecution
```

---

## P8-S31 — Delegation Guard PostgreSQL Protected Gate

### Acceptance

All DG-01..DG-12 SRS scenarios PASS using actual WC PostgreSQL.

### Regression

Existing P7 Golden B / Claim flows remain PASS.

### Gate

**P8.2A CLOSED**.

---

# 8. P8.3 — Human Approval Foundation

---

## P8-S32 — P8 Approval Transition Contract Pack

### Objective

Add additive P8 contracts for:

```text
NSL_WRITE
AGENT_FORMAL
BUSINESS_FORMAL
HumanGateView extension
ApprovalDecision
ApprovalEvent
```

Frozen files remain unchanged.

---

## P8-S33 — WC ApprovalWorkItem Persistence

### Objective

Create WC-owned durable approval task store.

### Logical tables

```text
wc_approval_work_item
wc_approval_decision
wc_approval_outbox
```

### State

```text
PENDING
APPROVED
REJECTED
EXPIRED
CANCELLED
```

---

## P8-S34 — Approval create_or_get Semantics

### Objective

Implement idempotent human-task creation.

### NSL source identity

```text
source_ref = ApprovalRequestId
```

### Tests

```text
same semantic create → same WorkItem
same ID / different binding → conflict
```

---

## P8-S35 — OA Approval Scopes

### Objective

Introduce/activate:

```text
approval:read
approval:decide
```

through existing OA authority model.

### No shortcuts

Do not create a separate approval user/permission database.

---

## P8-S36 — Approval Decision Authorization

### Objective

Perform fresh OA check immediately before decision commit.

### Required

```text
principal active
approval:decide
target principal/role/org/project match
```

### Failure

Zero WC decision mutation.

---

## P8-S37 — Immutable Decision / Duplicate Conflict

### Objective

Implement append-only decision history.

### Rules

```text
same exact terminal decision → idempotent
different later decision → conflict
```

---

## P8-S38 — Approval Decision Outbox

### Objective

Publish decision via durable outbox only after decision commit.

### Initial event types

```text
NSL_APPROVAL_DECIDED
BUSINESS_FORMAL_APPROVAL_DECIDED
```

---

## P8-S39 — EOS Approver Resolution API

### Objective

Use EOS Organization to resolve intended approver.

### Input

```text
requester
approval domain
risk
org/project context
policy
```

### Output

```text
principal_ref
position_type
org_unit_ref
resolution hash/ref
```

### Rule

Resolution is not security authorization.

---

## P8-S40 — IA Approval Inbox Read API

### Objective

Expose bounded eligible pending gates.

### Authorization

Current:

```text
approval:read
```

### Safety

No raw protected payload in list response.

---

## P8-S41 — IA Approval Detail / Decision API

### Objective

Expose:

```text
detail
APPROVE
REJECT
```

through WC-controlled action.

### Negative

UI cannot directly mutate NSL or EOS tables.

---

## P8-S42 — AE-WEB / IA Approval UI

### Objective

Render unified approval inbox with preserved domains.

### Must visually distinguish

```text
NSL_WRITE
AGENT_FORMAL
BUSINESS_FORMAL
```

### Playwright

Test:

```text
pending list
detail
approve
reject
unauthorized action
expired item
duplicate submit
```

---

## P8-S42A — Authentication-first AE Web Shell and View Routing Hardening

### Objective

Make employee authentication the only anonymous surface and expose the existing
AE Web capabilities through authenticated application views.

### Required behavior

```text
anonymous / expired -> employee login only
authenticated default -> Chat / Workspace
authenticated menu -> approvals, upload, documents, retrieval, artifacts
admin or operator only -> operations / diagnostics
logout / expiry -> immediate login return and protected DOM cleanup
```

Service readiness, runtime diagnostics, and audit details MUST NOT be rendered
before authentication. This Slice does not change a backend contract, database
table, or migration.

### Playwright

Verify desktop and mobile login-first rendering, authenticated menu routing,
employee operations-menu denial, absence of anonymous service probes, and
logout cleanup before entering the protected P8-S43 gate.

---

## P8-S43 — Human Approval Foundation Protected Gate

### Required

AP authorization/create/decision scenarios pass against actual WC/OA DB and IA
UI.

### Gate

**P8.3 CLOSED**.

---

# 9. P8.4 — NSL Approval Suspend / Resume Integration

---

## P8-S44 — Protected NSL ApprovalRequest Store

### Objective

Persist exact canonical NSL ApprovalRequest as protected evidence.

### Store

```text
protected_request_ref
approval_request_hash
```

### Rule

Full NSL request remains recoverable without leaking to generic WC rows.

---

## P8-S44A — ApprovalRequest PostgreSQL BYTEA Integration

### Objective

Keep the exact canonical NSL ApprovalRequest and its immutable metadata in one
AE PostgreSQL transaction.

### Decision

```text
ae_nsl_approval_request.approval_request_bytes BYTEA
```

The opaque `protected_request_ref`, hash, size, classification, and lineage
remain stable. The repository metadata projection never returns the private
bytes. Large or binary business payloads remain outside this envelope and are
referenced through `protected_payload_ref`.

### Migration Safety

The additive migration fails closed when a pre-existing metadata-only row has
no canonical bytes. It does not manufacture an empty or unverifiable request.

---

## P8-S45 — Generalize AE WaitRegistration

### Objective

Extend P7 wait store:

```text
WORK_RESULT
NSL_APPROVAL
```

### Migration

Generalize UUID-only external_ref to safe string identity without breaking
historical P7 rows.

---

## P8-S46 — NSL Approval Wait Binding

### Objective

Create one `NSL_APPROVAL` wait for exact:

```text
AgentExecution
ExecutableStep
NSLExecution
BusinessOperation
ApprovalRequest
checkpoint version
```

---

## P8-S47 — ApprovalPort Publication Adapter

### Objective

Implement NSL `ApprovalPort`.

### Required order

```text
checkpoint already persisted by NSL
→ ensure AE wait
→ WC create_or_get ApprovalWorkItem
```

### Failure

Retry same ApprovalRequestId.

---

## P8-S48 — Platform Approval Evidence Store

### Objective

Persist full immutable Platform evidence with:

```text
OA decision ref
ApprovalWorkItem ref
NSL binding hashes
evidence_integrity
```

---

## P8-S49 — NSL ApprovalEvidence Projection / Verifier

### Objective

Map Platform evidence to actual NSL public `ApprovalEvidence`.

### Verifier proves

```text
WC terminal decision
authority evidence
hash/provenance
tenant
approver
request identity
```

NSL performs semantic binding validation after that.

---

## P8-S50 — Typed AE Approval Event Inbox

### Objective

Extend external event inbox for:

```text
NSL_APPROVAL_DECIDED
```

without using fake WorkResult fields.

### Migration / schema

Event storage must support typed bounded event identity/refs.

---

## P8-S51 — NSLApprovalResumeSource

### Objective

Implement sibling of P7 WorkResult resume source.

### Validate

```text
running RESUME_EXECUTION
exact wait
exact event
exact approval request
exact evidence ref
resume_runtime_job_id
```

---

## P8-S52 — ApprovalResumeCoordinator Integration

### Objective

Invoke actual NSL:

```text
ResumeToken
ApprovalResumeCoordinator
```

using:

```text
same NSLExecutionId
same BusinessOperationId
exact checkpoint version
```

---

## P8-S53 — Approval Resume Protected PostgreSQL Gate

### End-to-end without EOS WRITE

```text
NSL prefix
→ WAITING_FOR_APPROVAL
→ WC decision
→ event
→ RESUME_EXECUTION
→ NSL approval valid
→ stop before business mutation
```

### Negative

Mismatch/expiry/reject scenarios pass.

### Gate

**P8.4 CLOSED**.

---

# 10. P8.5 — Governed WRITE → EOS

---

## P8-S54 — Platform RuntimePolicy / GovernedWrite Authorization Adapter

### Objective

Supply current Platform policy/authority evidence to NSL WriteGuard.

### Reuse

Frozen:

```text
GovernedWriteAuthorization
OperationTrustDecision
```

where compatible.

### Rule

No single ALLOW overrides another required DENY.

---

## P8-S55 — Durable NSL IdempotencyEvidencePort

### Objective

Provide production durable storage for NSL idempotency evidence.

### Important

Do not replace EOS idempotency.

Two layers:

```text
NSL execution idempotency evidence
EOS authoritative business idempotency
```

must bind the same actual IdempotencyKey/PayloadHash semantics.

---

## P8-S56 — Durable NSL WriteEvidencePort

### Objective

Persist:

```text
WRITE_REQUESTED
```

before provider/EOS invocation.

### Required refs

```text
NSLExecutionId
BusinessOperationId
WriteNodeId
IdempotencyKey
PayloadHash
WriteIntentHash
ApprovalRequestId
```

---

## P8-S57 — EOS WriteExecutionPort Adapter

### Objective

Implement NSL `WriteExecutionPort` backed by EOS Canonical Command API.

### It SHALL NOT

```text
embed EOS SQL
bypass EOS API
invent idempotency key
recalculate business operation identity
```

---

## P8-S58 — Fresh EOS Business Authorization

### Objective

Immediately before EOS mutation, perform fresh:

```text
finance:voucher-draft:create
```

authorization.

### Test

Upstream WriteGuard ALLOW + current EOS DENY => zero mutation.

---

## P8-S59 — Commit Outcome Mapping

### Objective

Map EOS result to actual NSL:

```text
WriteCommitted
WriteNotCommitted
WriteCommitUnknown
```

### No generic timeout retry.

---

## P8-S60 — Reconciliation Adapter

### Objective

When NSL returns/records UNKNOWN:

```text
AE → EOS BusinessOperation query
```

and preserve:

```text
RECONCILIATION_REQUIRED
```

until authoritative state known.

---

## P8-S61 — PostWriteVerificationPort Adapter

### Objective

Back NSL verification with EOS read-only Voucher query.

### Rule

No mutation.

---

## P8-S62 — Controlled WRITE Integration Gate

### End-to-end with controlled client

```text
valid Approval
→ WriteGuard
→ idempotency
→ WRITE_REQUESTED
→ EOS
→ COMMITTED
→ VERIFIED
```

### Negative

```text
EOS auth deny
idempotency conflict
payload hash mismatch
invalid Project/Account
```

zero duplicate mutation.

### Gate

**P8.5 CLOSED**.

---

# 11. P8.6 — Golden A Voucher Draft

---

## P8-S63 — Golden A Seed / Fixture Baseline

### Objective

Create stable test business data:

```text
tenant
user/principal
organization hierarchy
NVTProject
Mother Project
child Project
Account set
Agent/Skill admission
approval target
```

### Rule

Fixtures are deterministic and resettable.

---

## P8-S64 — Golden A Planning Capability Activation

### Objective

Allow live P6.5 provider to propose the Voucher Draft task while deterministic
binding resolves exact capability.

### LLM may suggest

```text
intent
project/account candidate
plan
```

### LLM may not set

```text
exact Project authority
Approval authority
IdempotencyKey
EOS commit state
```

---

## P8-S65 — Golden A IA → NSL Approval Journey

### Objective

Run actual:

```text
Prompt
→ Plan
→ LOCAL_SKILL
→ NSL prefix
→ Approval Inbox
→ human approve
→ resume
```

through actual AE/WC/OA PostgreSQL.

---

## P8-S66 — Golden A EOS Commit Journey

### Objective

Continue S65 to:

```text
WRITE_REQUESTED
→ actual EOS PostgreSQL
→ Voucher Draft
→ outbox
→ COMMITTED
→ verification read
```

---

## P8-S67 — Exactly-Once Golden A Retry Variants

### Prove business mutation count = 1 under:

```text
duplicate Approval event
duplicate RESUME_EXECUTION attempt
AE worker retry
EOS ACK loss after commit
result publication retry
```

---

## P8-S68 — Golden A Evidence Package

### Evidence

Record safe:

```text
Platform commit/tree
NSL release identity / wheel SHA
DB migration heads
CI/test IDs
BusinessOperationId
NSLExecutionId
ApprovalRequestId
ApprovalWorkItemId
VoucherRef
CommitState
VerificationStatus
mutation count
residue count
```

No raw protected payload.

### Gate

**P8.6 GOLDEN A CLOSED**.

---

# 12. P8.7 — BUSINESS_FORMAL / Multi-stage Approval

This phase starts only after Golden A Draft creation is stable.

---

## P8-S69 — EOS ApprovalPolicy Persistence

### Objective

Create policy model able to select:

```text
domain
risk
amount
project
account
transaction type
stages
quorum / SoD future fields
```

Initial scope may keep quorum simple.

---

## P8-S70 — EOS ApprovalInstance / Stage Persistence

### Objective

Implement immutable/staged business approval state.

### Required

```text
active stage
ordered stages
decision history
payload/protected-operation binding
```

---

## P8-S71 — BUSINESS_FORMAL WC Adapter

### Objective

Project active EOS stage into WC ApprovalWorkItem:

```text
approval_domain = BUSINESS_FORMAL
```

WC captures human work; EOS owns stage transition.

---

## P8-S72 — Leadership Ladder Resolution

### Objective

Support policy route:

```text
PART_LEAD
→ TEAM_LEAD
→ GROUP_LEAD
→ CEO
→ CHAIRMAN
```

### Tests

Policy using:

```text
1 stage
2 stages
3+ stages
```

without requiring all five.

---

## P8-S73 — EOS Stage Advance / Final ApprovalProof

### Objective

On validated WC decision:

```text
APPROVED
→ next stage or final proof

REJECTED
→ terminal rejected
```

Final proof is immutable and exact-binding-aware.

---

## P8-S74 — IA BUSINESS_FORMAL UX

### Objective

Display BUSINESS_FORMAL gates in same inbox but preserve distinct domain,
provider, target, and evidence.

---

## P8-S75 — Dual Approval Separation Acceptance

### Prove

```text
NSL_WRITE evidence
does not satisfy BUSINESS_FORMAL

BUSINESS_FORMAL proof
does not satisfy NSL_WRITE

AGENT_FORMAL
does not satisfy either
```

### Gate

**P8.7 CLOSED**.

---

# 13. P8.8 — Reliability / Reconciliation Closure

---

## P8-CA03 Attachment-Bearing Reliability Amendment

P8-S76 through P8-S86 retain their original numbering and objectives. They
also apply the normative reliability additions in
`P8_8_Pre_Entry_Repository_Consistency_and_Reliability_Preparation_Actions_v1.0.md`.

Across every applicable fault and recovery path, the following identities are
immutable:

```text
BusinessOperationId
IdempotencyKey
ApprovalRequest / WriteIntent / PayloadHash lineage
AttachmentManifestHash
attachment IDs
RustFS object identities
```

The attachment-bearing reliability matrix is:

| Slice | Required attachment-aware acceptance |
|---|---|
| P8-S76 | Lose the EOS commit response after committing one Voucher with three attachment associations; enter `UNKNOWN_COMMIT_STATE` without a second CREATE or upload. |
| P8-S77 | Resolve attachment-bearing UNKNOWN to `COMMITTED`, `NOT_COMMITTED`, or still `UNKNOWN`; preserve exact manifest, attachment, and object identity in every outcome. |
| P8-S78 | Keep one committed Voucher and its exact associations when post-write verification deterministically fails. |
| P8-S79 | Keep one committed Voucher and its exact associations when verification is unavailable or unknown. |
| P8-S80 | Retry outbox publication only; do not repeat Voucher mutation, association writes, or object upload. |
| P8-S81 | Replay approval delivery at most once semantically while preserving the original manifest-to-approval binding. |
| P8-S82 | Recover after checkpoint without duplicate approval, manifest, or attachment semantic work. |
| P8-S83 | Recover after `WRITE_REQUESTED` through idempotency and reconciliation without assuming `NOT_COMMITTED` or recreating evidence. |
| P8-S84 | Fail closed after current trust or authorization revocation, including protected attachment reads, before any new protected action. |
| P8-S85 | Detect manifest drift, attachment substitution, and cross-tenant object references without mutation, repair, disclosure, or tenant inference. |
| P8-S86 | Run at least one complete attachment-bearing reliability journey against actual AE/WC/OA/EOS test databases and RustFS, with zero duplicate mutation, zero duplicate object creation, and zero residue. |

Remote generation, embedding, and reranking providers are not required for
this reliability gate. Mandatory fault acceptance uses deterministic fixtures.

---

## P8-S76 — UNKNOWN_COMMIT_STATE Fault Injection

### Objective

Inject response-loss/ambiguous transport after possible EOS commit.

### Required

```text
no blind retry
RECONCILIATION_REQUIRED
```

### Implementation status

`CLOSED` on 2026-10-24.

The admitted NSL v0.2 WRITE request was dispatched exactly once to actual EOS.
After EOS committed one attachment-bearing Voucher, the accepted response was
discarded and AE observed:

```text
UNKNOWN_COMMIT_STATE
RECONCILIATION_REQUIRED
```

The one-shot fault adapter forbids a second dispatch. Protected evidence used
actual AE/WC/OA/EOS PostgreSQL databases and digest-pinned RustFS and proved:

```text
Voucher mutation count             = 1
BusinessOperation count            = 1
Outbox count                       = 1
Attachment association count       = 3
AttachmentManifestHash drift       = 0
Attachment/Object identity drift   = 0
RustFS duplicate object versions   = 0
test residue                        = 0
```

No reconciliation transition was performed in P8-S76. Authoritative
`COMMITTED`, `NOT_COMMITTED`, and still-`UNKNOWN` outcomes remain P8-S77 scope.

---

## P8-S77 — Reconciliation Outcomes

### Validate:

```text
UNKNOWN → COMMITTED
UNKNOWN → NOT_COMMITTED
UNKNOWN → still UNKNOWN
```

No duplicate Voucher Draft.

### Implementation status

`CLOSED` on 2026-10-24.

The existing AE reconciliation adapter now compares every EOS `COMMITTED`
attachment lineage against the original admitted NSL WRITE batch, manifest
hash, and canonical attachment ID set. Drift or malformed lineage remains
`UNKNOWN_COMMIT_STATE` and cannot be promoted to committed.

Actual AE/WC/OA/EOS test databases, the admitted NSL v0.2 wheel, and
digest-pinned RustFS proved:

```text
UNKNOWN -> COMMITTED              = PASS
UNKNOWN -> NOT_COMMITTED          = PASS
UNKNOWN -> still UNKNOWN          = PASS
EOS CREATE dispatches             = 1
Voucher Drafts                    = 1
attachment associations           = 3
manifest/attachment/object drift  = 0
duplicate RustFS object versions  = 0
test residue                      = 0
```

No API contract, table, or migration changed. P8-S78 is next.

---

## P8-S78 — COMMITTED + Verification FAILED

### Objective

Prove committed business state remains one Voucher even when verification
fails.

No CREATE retry.

### Implementation Status (2026-10-24)

**CLOSED.** Source audit confirmed the admitted NSL v0.2 verifier already
separates committed business state from verification status. The reusable
`EosVerificationMismatchFaultPort` now requires one exact healthy EOS
read-back before injecting a correctly bound deterministic mismatch.

Actual AE/WC/OA/EOS test databases, the admitted NSL v0.2 wheel, and
digest-pinned RustFS proved:

```text
EOS CREATE dispatches             = 1
authoritative verification reads  = 1
CommitState                       = COMMITTED
VerificationStatus                = FAILED
Voucher Drafts                    = 1
attachment associations           = 3
outbox rows                       = 1
manifest/attachment/object drift  = 0
duplicate RustFS object versions  = 0
test residue                      = 0
```

No production API contract, table, or migration changed. P8-S79 is next.

---

## P8-S79 — COMMITTED + Verification UNKNOWN

Same requirement for dependency timeout/unknown read outcome.

### Implementation Status (2026-10-24)

**CLOSED.** The reusable `EosVerificationTimeoutFaultPort` performs one exact
healthy EOS read-back and then discards that response as `TimeoutError`.
Admitted NSL maps it to `VerificationStatus.UNKNOWN` with
`VERIFICATION_TIMEOUT`, while the commit state remains `COMMITTED`.

Actual AE/WC/OA/EOS test databases, the admitted NSL v0.2 wheel, and
digest-pinned RustFS proved:

```text
EOS CREATE dispatches             = 1
authoritative verification reads  = 1
CommitState                       = COMMITTED
VerificationStatus                = UNKNOWN
verification reason               = VERIFICATION_TIMEOUT
Voucher Drafts                    = 1
attachment associations           = 3
outbox rows                       = 1
manifest/attachment/object drift  = 0
duplicate RustFS object versions  = 0
test residue                      = 0
```

No production API contract, table, or migration changed. P8-S80 is next.

---

## P8-S80 — Outbox Publication ACK Loss

### Objective

Retry event publication only.

Business mutation count remains one.

### Implementation Status (2026-10-24)

**CLOSED.** `SqlAlchemyEosOutboxPublisher` now locks one pending event with
PostgreSQL `FOR UPDATE SKIP LOCKED`, validates its payload hash, and records a
confirmed exact-binding receipt before changing the row to `PUBLISHED`. An
unconfirmed ACK increments `attempt_count` while keeping the row `PENDING`;
the business transaction coordinator is not part of this retry path.

Actual AE/WC/OA/EOS test databases and digest-pinned RustFS proved:

```text
EOS Voucher CREATE requests        = 1
outbox publication attempts        = 2
downstream acceptances             = 2
confirmed acknowledgements         = 1
unique semantic event IDs          = 1
final outbox state / attempts       = PUBLISHED / 2
Voucher Drafts                      = 1
attachment associations            = 3
outbox rows                         = 1
manifest/attachment/object drift    = 0
duplicate RustFS object versions    = 0
test residue                        = 0
```

No production API contract, table, or migration changed. P8-S81 is next.

---

## P8-S81 — Approval Event ACK Loss

### Objective

Duplicate/retried approval event creates at most one resume job and one
checkpoint consume.

**Status: CLOSED on 2026-10-24.**

The first acknowledgement is discarded only after AE has durably matched the
event and persisted its deterministic `RESUME_EXECUTION` job. The exact event
and approval binding are then retried. APPROVE, REJECT, and expiry scenarios
against actual `nex_ae_test` and `nex_wc_test` each produced one semantic
resume, one NSL checkpoint consume, no EOS mutation, and zero residue. Event
or approval-binding drift fails before redelivery. No production API contract,
table, or migration changed. P8-S82 is next.

---

## P8-S82 — Worker Crash After Checkpoint

### Objective

Restart restores exact wait/resume identity.

No duplicate ApprovalRequest semantic work.

---

## P8-S83 — Worker Crash After WRITE_REQUESTED

### Objective

On restart:

```text
do not assume NOT_COMMITTED
```

Use idempotency/reconciliation semantics.

---

## P8-S84 — Trust / Authorization Revocation

### Scenarios

```text
package trust invalid
OA approval authority revoked before decision
finance:voucher-draft:create revoked before mutation
```

All fail closed at current boundary.

---

## P8-S85 — Tamper / Cross-Tenant Matrix

### Include

```text
ApprovalEvidence tamper
PayloadHash mismatch
WriteIntentHash mismatch
cross-tenant Project
cross-tenant Account
cross-tenant attachment
stale Claim delegation
```

Zero unauthorized mutation.

---

## P8-S86 — Full Reliability Protected Gate

Run all fault variants using actual service DBs.

### Gate

**P8.8 CLOSED**.

---

# 14. P8.9 — Full Gate / Final As-Built Freeze

---

## P8-S87 — Contract / OpenAPI / Example Hygiene

### Run

```text
all JSON Schema
all positive examples
all negative examples
OpenAPI parse
producer/consumer parity
terminology scan
reference scan
```

Zero known P0/P1 contract drift.

---

## P8-S88 — Full Repository Regression

### Required

```text
P4
P5
P6
P6.5
P7
P8
```

all regression suites.

No P7 Claim/WorkResult behavior regression.

---

## P8-S89 — Coverage Closure

Platform minimum:

```text
Statement >= 96%
Branch    >= 94%
```

No exclusion manipulation to make coverage pass.

NSL native certification remains independently PASS.

---

## P8-S90 — Actual DB Full Gate

Run protected:

```text
AE
WC
OA
EOS
```

PostgreSQL suite with reset and residue verification.

---

## P8-S91 — IA Playwright Full Gate

Cover:

```text
NSL_WRITE
BUSINESS_FORMAL
approve
reject
expired
unauthorized
duplicate
domain distinction
```

---

## P8-S92 — Golden A + Fault Re-run

Re-run Golden A and required reliability variants against the final candidate
commit.

---

## P8-S93 — P8 Final As-Built Baseline / P9 Handoff

Create final document containing:

```text
final commit/tree
migration heads
contract versions
NSL wheel identity
Golden A evidence
fault evidence
coverage
known deferred scope
P9 entry invariants
```

### Final state

```text
P8 CLOSED
P8 Golden A CLOSED
P8 Reliability CLOSED
P9 ENTRY AUTHORIZED
```

---

# 15. Dependency Graph

High-level:

```text
P8-S01..S06
     │
     ├───────────────────────┐
     ▼                       ▼
P8-S07..S22              P8-S23..S31
EOS Foundation            Delegation Guard
     │                       │
     └──────────────┬────────┘
                    ▼
              P8-S32..S43
              Human Approval
                    ▼
              P8-S44..S53
              NSL Wait/Resume
                    ▼
              P8-S54..S62
              Governed WRITE
                    ▼
              P8-S63..S68
                 Golden A
                    ▼
              P8-S69..S75
              Formal Approval
                    ▼
              P8-S76..S86
                Reliability
                    ▼
              P8-S87..S93
                 Full Gate
```

---

# 16. Parallelism Rules

Allowed:

```text
P8.2 EOS Foundation
||
P8.2A Delegation Guard
```

after P8.1.

Limited parallelism is also possible between:

```text
EOS Organization
and
Voucher domain core
```

after DB/service foundation.

Not allowed:

```text
P8.4 NSL Approval Resume
before P8.3 ApprovalWorkItem semantics are stable

P8.5 live WRITE
before P8.4 resume semantics pass

P8.6 Golden A
before P8.5 controlled WRITE gate

P8.7 Formal Approval
as a blocker for P8.6 Draft Golden A
```

---

# 17. Recommended Commit Boundaries

Each Slice SHOULD produce one commit unless a source-preserving refactor requires
a separate preceding commit.

Examples:

```text
feat(p8): add NSL v0.2 backend profile
feat(p8): add EOS service foundation
feat(p8): persist WC delegation lineage
feat(p8): enforce delegation root budget
feat(p8): add WC approval work item
feat(p8): add NSL approval wait registration
feat(p8): bridge approval evidence into NSL
feat(p8): add EOS voucher draft command
test(p8): close Golden A protected acceptance
fix(p8): preserve unknown commit reconciliation
docs(p8): freeze final as-built baseline
```

Commit names are examples, not mandatory exact text.

---

# 18. Migration Strategy

Migration changes SHALL be isolated by service.

Recommended order:

```text
AE:
  NSL v0.2 binding/wait/event extensions

WC:
  delegation lineage
  approval work/decision/outbox

EOS:
  bootstrap
  organization
  NVT/project/account
  business operation/idempotency/outbox
  voucher
  formal approval
```

Every migration Slice SHALL test:

```text
fresh DB
upgrade from immediate prior head
historical rows
constraint violation
service restart
```

---

# 19. Test Database Rules

For each DB service:

```text
reset owned test database
apply migrations
seed only owned test data
run tests
verify owned residue
```

P8 shall not depend on developer-machine leftover rows.

EOS uses:

```text
nex_eos_test
```

for test execution.

---

# 20. Coverage Strategy

Coverage should be closed progressively.

After every major Gate:

```text
P8.1
P8.2 / 2A
P8.3
P8.4
P8.5
P8.6
P8.7
P8.8
```

record:

```text
statement coverage
branch coverage
new uncovered branch classes
```

Do not defer all coverage recovery to P8-S89.

---

# 21. Evidence Strategy

Protected Gate evidence SHOULD include:

```text
source commit/tree
test command
test count/pass/fail
coverage
migration head
service versions
DB identity
important semantic counts
zero residue
```

For Golden/Fault WRITE:

```text
business mutation count
idempotency disposition
CommitState
VerificationStatus
reconciliation state
```

No raw prompts, credentials, document bytes, or private approval contents.

---

# 22. Slice Risk Classification

### High Risk

```text
S01 release identity
S26 parent Claim authority
S28/S29 concurrent budget
S30 cycle detection
S36 approval authorization
S45 wait migration
S49 evidence verifier
S52 NSL resume integration
S56 WRITE_REQUESTED persistence
S57 EOS WriteExecutionPort
S59 Commit mapping
S60 reconciliation
S66 Golden A commit
S76-S83 fault recovery
```

These SHOULD receive focused code review and protected PostgreSQL evidence.

### Medium Risk

```text
organization
NVT hierarchy
Voucher aggregate
IA HumanGate
formal approval stages
```

### Low Risk

```text
service skeleton
readiness/version
safe projections
documentation
```

Risk level does not waive tests.

---

# 23. Stop-the-Line Conditions

Implementation SHALL stop and return to contract review if any Slice discovers:

```text
Frozen ownership contradiction
need to modify NSL semantic behavior from Platform
need to bypass EOS API with direct DB WRITE
need to treat BUSINESS_FORMAL as NSL_WRITE
need to reuse WorkResult event shape for Approval
need to blind retry UNKNOWN_COMMIT_STATE
need to weaken package trust
need to reduce current authorization checks
need to exceed Project depth by hidden denormalization
```

Do not patch around such findings.

---

# 24. Deferred Scope Ledger

Explicitly deferred beyond P8 Golden A:

```text
NVT token economics
full ledger / P&L
procurement
fiscal close
attachment content approval-manifest policy
RustFS full document lifecycle
Email/Push approval
ActingAuthority
bulk controlled WRITE
complex quorum approval
parallel approval stages
multiple NSL WRITE nodes
EOS microservice split
```

A deferred item SHALL not be silently implemented inside an unrelated Slice.

---

# 25. P8 Gate Summary

| Gate | Required Slices | Exit |
|---|---:|---|
| P8.1 NSL Admission | S01-S06 | exact v0.2 runtime admitted |
| P8.2 EOS Foundation | S07-S22 | EOS minimum domain operational |
| P8.2A Delegation Guard | S23-S31 | bounded recursive delegation |
| P8.3 Human Approval | S32-S43 | durable IA/WC/OA approval |
| P8.4 NSL Resume | S44-S53 | real NSL approval wait/resume |
| P8.5 Governed WRITE | S54-S62 | safe WRITE reaches EOS |
| P8.6 Golden A | S63-S68 | exactly-one Voucher Draft E2E |
| P8.7 Formal Approval | S69-S75 | BUSINESS_FORMAL multi-stage |
| P8.8 Reliability | S76-S86 | fault/reconcile semantics closed |
| P8.9 Full Gate | S87-S93 | P8 frozen / P9 entry |

---

# 26. Recommended Immediate Start

The first implementation batch should be intentionally small:

```text
Batch P8-A

S01 Actual NSL v0.2 Wheel Identity Closure
S02 NSL v0.2 Wheel Lock Contract
S03 NSL_V02_IN_PROCESS Backend Profile
S04 Installed v0.2 Package Readiness
S05 v0.2 Public API Adapter Foundation
S06 v0.2 Compatibility Smoke
```

Reason:

```text
all later P8 runtime work depends on exact NSL v0.2 artifact identity
```

Do not start EOS live WRITE integration until this gate is closed.

---

# 27. Second Implementation Batch

After P8.1:

```text
Batch P8-B1 — EOS
S07-S22

Batch P8-B2 — Delegation
S23-S31
```

These may proceed in parallel because their authoritative data/state boundaries
are independent.

They converge at Human Approval / Golden A integration.

---

# 28. Final Definition of Done

P8 implementation is complete only when:

```text
NSL exact release is admitted
v0.1 regression remains compatible

EOS authoritative Voucher Draft exists
NVTProject / Project hierarchy works
attachment reference boundary is ready

Delegation is bounded by depth/fan-out/root/cycle/current Claim

Human approval is durable
IA presents it
OA authorizes it
NSL validates exact evidence

WRITE_REQUESTED precedes business mutation
EOS current authorization passes
idempotency prevents duplicate mutation
UNKNOWN_COMMIT_STATE never blind retries
verification never recreates committed work

Golden A mutation count = 1
fault variants preserve mutation count
BUSINESS_FORMAL remains distinct
Platform coverage >= 96/94
NSL certification remains PASS
Full Gate PASS
P8 Final As-Built baseline frozen
```

---

# 29. Final Implementation Position

P8 implementation intentionally proceeds from the outside inward:

```text
exact NSL release
        ↓
service/domain foundations
        ↓
bounded delegation
        ↓
human approval
        ↓
NSL resume
        ↓
governed WRITE
        ↓
Golden A
        ↓
formal approval
        ↓
fault/reconciliation
        ↓
freeze
```

This sequencing minimizes the chance that the first real business WRITE becomes
the place where package identity, human workflow, hierarchy, authorization,
idempotency, and recovery semantics are all discovered at once.

> **Every Slice should leave the repository in a testable, explainable, and safer state than the Slice before it.**
