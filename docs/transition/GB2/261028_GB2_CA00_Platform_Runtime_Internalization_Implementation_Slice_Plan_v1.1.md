# GB2-CA00 — Platform Runtime Internalization & Smoke-to-Product Promotion
# Implementation Slice Plan v1.1

**Status:** PRE-IMPLEMENTATION / SOURCE-BACKED IMPLEMENTATION PLAN / v1.1 / GB2-CA00A RECONCILED
**Program:** NeX Platform v2.1
**Gate:** GB2-CA00 — Platform Runtime Internalization & Smoke-to-Product Promotion
**Source Audit / PAD:** `261028_GB2_CA00_Platform_Runtime_Internalization_and_Smoke_to_Product_Promotion_Audit_v1.1.md`
**Consistency Closure:** `261028_GB2_CA00A_Pre_Implementation_Document_Consistency_Closure_v1.0.md`
**Successor:** Golden B v2 — Manufacturing Delegation Full Journey
**Repository:** `nurigitdev/2607_nex_platform`
**Branch:** `transition/p4-agent-runtime-foundation`
**Observed HEAD:** `a066dcffa4097cb0d33daf5e749e9e24c7481679`
**Accepted P9 Corrected Executable Baseline:** `a4ef2f76d2b34e937f8e30316743302126c435ed`
**Date:** 2026-10-28

---

# 1. Purpose

This plan converts the GB2-CA00 source audit and pre-architecture decisions
into bounded implementation slices.

The objective is not to add a new business feature.

The objective is to close the gap:

```text
Implemented Capability
!=
Installed Product Runtime
```

before Golden B v2 business implementation starts.

GB2-CA00 promotes Demo-validated runtime behavior into the canonical current
Platform while preserving all P7/P8/P9 semantics.

The five mandatory workstreams are:

```text
WS1  Promote AE Runtime / WC Delivery / EOS Outbox workers
WS2  Extract generic installed AE runtime composition
WS3  Generalize fixture-based domain activation into a registry
WS4  Prohibit Smoke-owned runtime transitions in Golden Journey acceptance
WS5  Separate OpenBao/RustFS/provider provisioning from runtime readiness
```

---

# 2. Entry Baseline

Current P9 corrected baseline is closed and revalidated.

Accepted P9 evidence:

```text
P9-S31A executable commit = a4ef2f76d2b34e937f8e30316743302126c435ed
P9 Foundation             = CLOSED / REVALIDATED
P9.5                      = DEFERRED

Repository Full Gate
  pytest                  = 18,268 passed
  protected skips         = 131
  statement coverage      = 96.01%
  branch coverage         = 95.22%
  exit code               = 0
```

Current documentation-only descendant:

```text
a066dcffa4097cb0d33daf5e749e9e24c7481679
docs(wa): freeze P9 privacy corrective closure
```

GB2-CA00 must preserve the P9 executable semantics unless a Slice explicitly
states otherwise.

---

# 3. Current vs Target Runtime Topology

Current Platform baseline:

```text
artifacts = 9

processes = 17
  APIs/background/web from current P9 topology
```

Current P9 Platform already includes:

```text
nex-wa-evidence-consumer
```

as a first-class `job_claiming` worker.

It is a reference implementation, not a promotion target.

Known missing first-class domain processes are exactly:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

Target GB2-CA00 topology:

```text
artifacts = 9
processes = 20
```

No new OCI artifact is expected.

The three new process bindings reuse:

```text
nex-ae-runtime
nex-wc-runtime
nex-eos-runtime
```

The AE dispatcher remains an embedded component of the AE Agent Runtime worker
unless a later source-backed review proves an independent process is necessary.

---


# 3A. First-Class Worker Reference Baseline

`nex-wa-evidence-consumer` is already part of the current P9 Platform and is
not a GB2-CA00 promotion target.

It is the reference baseline for worker Platformization.

The implementation objective is:

> **P9에서 NeX-WA worker에 적용한 수준의 first-class runtime
> integration을, P8-DEMO에서만 설치형으로 존재했던 AE/WC/EOS domain
> workers에도 동일한 수준으로 승격하여 Platform에 내재화한다.**

Current/target counting is therefore:

```text
Current P9 Platform
  artifacts = 9
  processes = 17
  includes  = nex-wa-evidence-consumer

GB2-CA00 adds only
  + nex-ae-agent-runtime-worker
  + nex-wc-event-delivery-worker
  + nex-eos-outbox-publisher

Target
  artifacts = 9
  processes = 20
```

The WA worker establishes the expected common integration characteristics:

```text
first-class process identity
deployment artifact binding
canonical packaged entrypoint
truthful work capability
owner-local persistence dependency
heartbeat/readiness
graceful shutdown
restart/recovery
idempotent settlement
protected installed acceptance
```

The three promoted workers do not need to copy the WA JobQueue algorithm.

They preserve owner-specific execution models:

```text
AE  = RuntimeJob / dispatcher / Agent Runtime worker
WC  = event/result delivery worker
EOS = outbox publisher
WA  = evidence JobQueue consumer [existing reference]
```

No Slice SHALL accidentally re-register or redesign the WA worker as part of
GB2-CA00.

---

# 4. Core Invariants

All Slices inherit:

```text
GB2-INV-00
NeX-WA evidence consumer is the existing first-class worker reference.
AE Runtime / WC Delivery / EOS Outbox workers SHALL be promoted to the same
Platform integration level without changing their owner-specific semantics.

GB2-INV-01
WorkItem existence != execution authority.

GB2-INV-02
Claim = background execution authority.

GB2-INV-03
CLAIMED_WORKITEM remains the only current CA/PA/EA new-execution trigger.

GB2-INV-04
AgentResult alone != background success.

GB2-INV-05
Required ResultDelivery ACK remains part of completion.

GB2-INV-06
No second dispatcher, worker framework, approval engine, or result model.

GB2-INV-07
Business Capability identity != execution Skill identity.

GB2-INV-08
Business fixtures may seed authoritative source facts.

GB2-INV-09
Runtime transition fixtures are forbidden for Golden Journey acceptance.

GB2-INV-10
After a business request enters the Platform, required transitions must be
caused by installed Platform processes or admitted APIs.

GB2-INV-11
Demo code may wrap canonical Platform code; canonical Platform runtime may not
depend on demo-only modules or fixture files.

GB2-INV-12
Application business requests do not provision infrastructure resources.

GB2-INV-13
Configured dependency != ready dependency.

GB2-INV-14
Smoke proves Platform behavior; Smoke is not the owner of Platform behavior.
```

---

# 5. Non-Goals

GB2-CA00 SHALL NOT introduce:

```text
Golden B manufacturing business logic
new WorkItem model
new Claim model
new approval domain
new AgentExecution trigger
new NSL syntax
new external broker
new Scheduler
autonomous PA
P9.5 ContributionCandidate
Golden C
new WA schema
new accounting semantics
```

If implementation begins requiring one of these, stop and return to
architecture review.

---

# 6. Implementation Strategy

The work is divided into four execution bands.

```text
Band A — Canonical Runtime Composition and Process Promotion
  S01-S08

Band B — Domain Activation Productization
  S09-S11

Band C — Testing Contract and Dependency Readiness
  S12-S16

Band D — Installed Current-Platform Acceptance and Freeze
  S17-S20
```

---

# 7. Workstream Mapping

| Workstream | Slices |
|---|---|
| WS1 Process topology promotion | S01, S02, S05-S08 |
| WS2 Generic AE runtime composition | S03-S04 |
| WS3 Domain activation registry | S09-S11 |
| WS4 Smoke/Golden Journey testing contract | S12, S17-S19 |
| WS5 Deployment dependency readiness | S13-S16 |
| Final installed acceptance / handoff | S18-S20 |

---

# 8. Quality Policy

Repository development process uses:

```text
Slice Gate
Checkpoint Gate
Full Gate
```

GB2-CA00 adopts the stronger current project floor:

```text
Statement >= 96%
Branch    >= 94%
```

for:

```text
changed source
affected owning services
GB2-CA00 closure
repository Full Gate
```

The generic historical Full Gate minimum is not used to lower this project
floor.

The accepted comparison baseline is:

```text
18,268 passed / 131 protected skips
96.01% statement
95.22% branch
```

Any reduction must be explained.

Because several Slices change:

```text
_shared runtime
cross-service process topology
production entrypoints
authentication/trust
production bootstrap
```

risk-escalated Checkpoint or Full Gates are explicitly scheduled below.

---

# 9. Commit Discipline

Every source Slice:

```text
1. inspect current source
2. refactor before feature when structure is wrong
3. change one bounded concern
4. add focused regression
5. run required protected evidence
6. run Slice/Checkpoint/Full Gate
7. git diff --check
8. commit only after PASS
9. synchronize before next Slice
```

Do not combine a large structural refactor with unrelated feature behavior.

---

# 10. Expected Migration / Contract Impact

Default expectation:

```text
database migration       = NO
new business table       = NO
new Agent state          = NO
new Work state           = NO
new public business API  = NO
```

Expected additive contracts may include:

```text
runtime process metadata
dependency readiness projection
testing evidence metadata
```

If a Slice discovers that a new persistent table is necessary, stop and
perform a source-backed amendment before continuing.

---

# 11. Band A — Runtime Composition and Process Promotion

## GB2-CA00-S01 — Platformization Inventory and Target Contract Freeze

### Goal

Freeze the exact current/demo/target ownership before code changes.

### Deliverable

Create:

```text
docs/transition/GB2/
GB2_CA00_Platform_Runtime_Process_and_Dependency_Inventory_v1.0.md
```

Inventory every relevant item using:

```text
P = PLATFORM CANONICAL
D = DEMO PROFILE
T = TEST ONLY
H = HISTORICAL EVIDENCE
X = INVALID RUNTIME DEPENDENCY
```

Minimum inventory:

```text
p8_demo_runtime_composition.py
p8_demo_controlled_skill.py
p8_demo_semantic_activation.py
demo_runtime.py [AE/WC/EOS]
demo_processes.py
demo_domain_activation.py
demo_domain_installation.py

agent_runtime_dispatcher.py
agent_runtime_worker.py
multi_step_engine.py
semantic_candidate_admission.py
nsl_approval_resume.py
workspace_result_publication.py

WC event/outbox/result delivery components
EOS outbox publication components

current process_manifest
current deployment_artifacts
current deployment_entrypoints
production_container_bootstrap

OpenBao resolver/provisioning
object storage client/lifecycle/IAM
provider preflight/runtime
```

### Required Matrices

```text
Process
Owner
Artifact
Entrypoint
Execution Model
Database
Dependencies
Heartbeat
Work Capability
Restart Contract
Current Status
Target Status
```

and:

```text
Module
Classification
Imported By Product Runtime?
Imported By Demo?
Must Promote?
Must Remain Historical?
```

### Tests

Documentation-only:

```text
path/reference checks
no contradictory process counts
git diff --check
```

### Exit

```text
target process count = 20 confirmed
target artifact count = 9 confirmed
no unresolved owner ambiguity
S02 authorized
```

---

## GB2-CA00-S02 — Runtime Process Capability Taxonomy

### Goal

Make Platform topology distinguish a real domain worker from a lifecycle-only
process.

### Current Problem

Current packaged capability vocabulary contains:

```text
request_serving
static_serving
job_claiming
lifecycle_only
```

This is not expressive enough for:

```text
WC event delivery
EOS outbox publication
```

### Implement

Extend runtime process capability metadata with bounded categories such as:

```text
job_claiming
event_delivering
outbox_publishing
scheduled_maintenance
lifecycle_only
```

Exact naming may be normalized.

Rules:

```text
lifecycle_only
!= domain work enabled

domain worker
→ must have an executable work loop
```

### Likely Source Areas

```text
services/_shared/nex_runtime/deployment_entrypoints.py
services/_shared/nex_runtime/process_manifest.py
services/_shared/nex_runtime/topology.py [only if needed]
tests/*
```

### Do Not Yet

Do not add the three missing workers to current topology until their canonical
entrypoints exist.

### Tests

Add focused tests proving:

```text
known process capability accepted
unknown capability rejected
lifecycle_only cannot claim domain-work acceptance
job_claiming/event_delivering/outbox_publishing remain distinct
historical manifests remain compatible
```

### Gate

Because shared runtime changes:

```text
Slice Gate
+
risk-escalated Checkpoint Gate
```

### Exit

```text
process capability model ready for worker promotion
no domain semantics changed
```

---

## GB2-CA00-S03 — Generic AE Installed Runtime Composition Extraction

### Goal

Extract the reusable P6/P8 installed runtime composition from Demo-specific
configuration.

### Source

Refactor from:

```text
services/nex-ae-api/nex_ae_api/p8_demo_runtime_composition.py
```

### Create

A canonical service-owned module, for example:

```text
nex_ae_api/runtime_composition.py
```

Exact name is implementation choice.

### Generic Composition SHALL Own

```text
SqlAlchemyRuntimeJobQueue
SqlAlchemyMultiStepEngine
SqlAlchemyAgentRuntimeDispatcher
SqlAlchemyAgentRuntimeAssignmentSource
P5StepExecutionWorker
AgentRuntimeWorkerLifecycle
run_bounded_agent_runtime_worker
continuation source
executor registry
result closer
result publisher
optional post-completion notifier
```

### Generic Composition SHALL NOT Know

```text
Golden A
FINANCE.CREATE_VOUCHER_DRAFT
FINANCE.VOUCHER_DRAFT_CREATE
voucher
Chairman demo
P8 demo fixture
demo NSL bundle path
demo Skill root
/home/... local path
```

### Interface Direction

The generic factory accepts scenario/domain execution dependencies.

Conceptually:

```text
RuntimeExecutorProfile
  ├─ executor registry / handlers
  ├─ backend profiles
  ├─ package readiness
  └─ continuation handlers

GenericInstalledRuntimeFactory
  ├─ dispatcher
  ├─ worker
  ├─ engine
  └─ result closer
```

### Preserve

```text
RuntimeJob semantics
MultiStepEngine semantics
WAIT / RESUME semantics
NSL Approval semantics
Result finalization semantics
```

No state-machine rewrite.

### Tests

New focused tests:

```text
generic composition builds with non-demo fake executor profile
non-WAITING step schedules successor
WAITING step does not schedule successor
claimed_count remains canonical worker counter
result closer invoked after cycle
missing executor profile fails closed
```

### Gate

AE Slice Gate:

```text
Statement >= 96%
Branch >= 94%
```

### Exit

```text
generic installed AE composition exists
zero imports from p8_demo_* inside generic module
```

---

## GB2-CA00-S04 — P8-DEMO Rebind Through Generic AE Factory

### Goal

Preserve historical P8-DEMO behavior while removing duplicate orchestration.

### Change

Convert:

```text
p8_demo_runtime_composition.py
```

into a thin Demo adapter over the generic composition.

It may still provide:

```text
P8DemoControlledSkillRuntime
Demo fixture-backed Golden A profile
Demo package paths
```

but it must no longer own:

```text
dispatcher construction semantics
worker loop semantics
step scheduling semantics
result closer orchestration
```

### Required Regression

Existing P8-DEMO acceptance:

```text
S10B installed runtime
S10C result closure
relevant S11 Golden A runtime
```

must remain behaviorally equivalent.

### Explicit Check

Generic product module SHALL NOT import:

```text
p8_demo_runtime_composition
p8_demo_controlled_skill
demo_fixture
```

### Exit

```text
P8-DEMO behavior preserved
Demo is wrapper/profile
generic factory is owner of runtime composition
```

---

## GB2-CA00-S05 — Promote AE Agent Runtime Worker

### Goal

Make AE Agent Runtime a first-class current Platform process.

### Create/Promote

Canonical service-owned process entrypoint, conceptually:

```text
python -m nex_ae_api.agent_runtime_process
```

Exact module name may differ.

It SHALL use the generic factory from S03.

It SHALL NOT use:

```text
nex_ae_api.demo_runtime
```

as its canonical current Platform command.

### Current Process ID

```text
nex-ae-agent-runtime-worker
```

### Required Platform Wiring

```text
process manifest
deployment artifact binding
packaged entrypoint
database env
worker heartbeat
SIGTERM
restart
dependency list
work capability = job_claiming
```

### Runtime Readiness

When enabled, readiness must prove:

```text
AE DB current
dispatcher available
worker profile valid
executor registry available
configured executor kinds available
configured backend profiles available
package readiness PASS when package is required
```

A boolean flag alone is insufficient.

### Protected Worker Acceptance

Seed only a bounded executable test work item/runtime job through normal
admitted service setup.

Then prove the installed worker:

```text
claims one real assignment
runs handler
settles runtime job
emits heartbeat
survives restart
does not double-execute
```

This acceptance may use a deterministic non-business executor profile.

Evidence classification:

```text
PROTECTED_COMPONENT
```

This Slice proves the AE worker boundary only. Its bounded admitted setup does
not constitute `INSTALLED_PLATFORM` or `GOLDEN_JOURNEY` continuity evidence
and does not create an exception to the S12 post-request mutation rule.

### Gate

Because this changes installed production process topology:

```text
Slice Gate
+
Checkpoint Gate #1
```

### Exit

```text
AE Agent Runtime worker is current Platform first-class
no Demo process manifest required
```

---

## GB2-CA00-S06 — Promote WC Event-Delivery Worker

### Goal

Make WC delivery a first-class current Platform process.

### Current Source

P8-DEMO currently runs:

```text
python -m nex_wc.demo_runtime events
```

### Target

Create a canonical service-owned process entrypoint using existing WC
components.

Conceptual process:

```text
nex-wc-event-delivery-worker
```

### Must Reuse

Existing:

```text
handoff delivery
WorkResult delivery
approval event delivery
service-local JobQueue
outbox/retry semantics
signed AE transport
worker heartbeat
```

### Must Not

Do not create a new delivery queue or event model.

### Protected Acceptance

Create one admitted pending delivery through the owning WC API/domain service.

Then prove installed worker:

```text
claims/delivers
persists delivery result
replay is idempotent
restart resumes pending work
wrong signed trust fails closed
```

Evidence classification is `PROTECTED_COMPONENT`. The admitted pending
delivery is valid for this owner-component test but cannot be cited as Golden
Journey continuity evidence.

### Exit

```text
WC delivery process is current Platform first-class
canonical command has no demo_runtime dependency
```

---

## GB2-CA00-S07 — Promote EOS Outbox Publisher

### Goal

Make EOS outbox publication a first-class current Platform process.

### Current Source

P8-DEMO:

```text
python -m nex_eos.demo_runtime outbox
```

### Target

Canonical service-owned process:

```text
nex-eos-outbox-publisher
```

using the existing EOS outbox publisher implementation.

### Required Wiring

```text
current process manifest
artifact binding to nex-eos-runtime
packaged direct entrypoint
database environment
signed downstream transport
heartbeat
restart
outbox retry
work capability = outbox_publishing
```

### Protected Acceptance

Create one legitimate EOS outbox item through an owning business operation or
bounded source-backed fixture setup.

Then installed publisher must:

```text
publish once
record result
replay safely
recover after restart
```

Evidence classification is `PROTECTED_COMPONENT`. The bounded outbox setup
proves publisher behavior only and cannot satisfy the installed Golden Journey
acceptance in S18.

### Exit

```text
EOS publisher is current Platform first-class
no Demo entrypoint dependency
```

---

## GB2-CA00-S08 — Current Process Topology Closure

### Goal

Close WS1 as one coherent current Platform topology.

### Expected Current Target

```text
artifacts = 9
processes = 20
```

New current process bindings:

```text
nex-ae-agent-runtime-worker -> nex-ae-runtime
nex-wc-event-delivery-worker -> nex-wc-runtime
nex-eos-outbox-publisher -> nex-eos-runtime
```

### Update

At minimum:

```text
CURRENT_BACKGROUND_PROCESS_IDS
CURRENT_PROCESS_ARTIFACT_BINDINGS
current packaged entrypoints
current process/environment manifest
runtime startup graph
production responsibility inventory
deployment coupling audits
```

### Required Invariant

All three are real work processes.

None may be classified as:

```text
lifecycle_only
```

### Protected Topology Test

Start/check all current Platform processes sufficiently to prove:

```text
canonical command exists
package imports
DB dependency resolves
heartbeat/readiness works
work-loop readiness is truthful
```

### Full Gate #1

Run Repository Full Gate because:

```text
_shared runtime
3 services
deployment topology
packaged commands
```

have all changed.

### Exit — CA00-RUNTIME-01

```text
9 artifacts / 20 processes
3 promoted domain workers
Full Gate PASS
coverage >= 96/94
```

---

# 12. Band B — Domain Activation Productization

## GB2-CA00-S09 — DomainIntentActivator Registry Foundation

### Goal

Remove domain-specific activation from semantic admission core.

### Current Problem

Product semantic admission directly imports:

```text
p8_demo_semantic_activation.build_p8_demo_intent_activators
```

### Introduce

Canonical concept:

```text
DomainIntentActivator
DomainIntentActivatorRegistry
```

### Minimum Registry Contract

Each registration should bind:

```text
capability_id
version/source identity
activator
```

Required behavior:

```text
duplicate capability → fail closed
unknown optional capability → no activation
unknown required capability → fail closed
deterministic resolution
stable registration projection/hash
```

### Semantic Admission Change

`semantic_candidate_admission` receives or builds the registry through a
canonical product builder.

It must not import `p8_demo_semantic_activation`.

### Tests

```text
empty registry
single activator
duplicate rejection
unknown required activation
deterministic resolution
replay equality
```

### Exit

```text
semantic admission is domain-agnostic
```

---

## GB2-CA00-S10 — Productize Golden A Finance Activator

### Goal

Make Golden A a registered finance domain profile rather than a special Demo
dependency of semantic admission.

### Preserve

```text
Capability = FINANCE.CREATE_VOUCHER_DRAFT
Skill      = FINANCE.VOUCHER_DRAFT_CREATE
```

These identities remain distinct.

### Extract

Move reusable Golden A activation logic into a canonical finance/Golden-A
module.

It SHALL NOT require generic semantic admission to load:

```text
NEX_AE_DEMO_FIXTURE
NEX_AE_DEMO_BASE_FIXTURE
scripts/smoke/data/*
scripts/deployment/data/*
```

### Data Source Direction

The canonical activator should resolve authoritative binding from product
sources/repositories/configuration.

Demo fixture may still seed:

```text
Project
account master
requester/approver
business values
```

but fixture parsing is outside the canonical activator.

### Tests

```text
finance capability resolves
skill binding remains distinct
project/account authority mismatch fails closed
no fixture path required by generic app attachment
Golden A replay deterministic
```

### Risk Gate

Semantic admission is core AE behavior.

Run:

```text
AE Slice Gate
+
Checkpoint Gate #2
```

### Exit

```text
Golden A exists as product domain activator
semantic core has no demo fixture dependency
```

---

## GB2-CA00-S11 — Capability / Skill Registration and Demo Seed Boundary

### Goal

Separate:

```text
business source fixture
```

from:

```text
Platform capability existence
```

### Current Risk

P8-DEMO journey may seed capability snapshots or rely on fixture admission
metadata during test preparation.

### Target

Capability/Skill availability must come from a canonical Platform mechanism.

Allowed initial mechanisms:

```text
versioned built-in capability registration
admitted Skill Artifact package metadata
deployment-time capability registry seed
```

Use the smallest source-backed existing mechanism.

### Demo Role After S11

Demo data may seed:

```text
Project
accounts
user
approval target
scenario amount/content
```

It may not define the fact that:

```text
FINANCE.CREATE_VOUCHER_DRAFT capability exists
```

through an arbitrary JSON fixture.

### Regression

P8-DEMO must continue to run through the canonical capability registration.

### Exit — CA00-DOMAIN-01

```text
generic semantic admission registry-based
Golden A registered as product profile
capability/Skill boundary preserved
demo fixture no longer defines product capability existence
```

---

# 13. Band C — Testing Contract and Dependency Readiness

## GB2-CA00-S12 — Golden Journey Testing Contract and Enforcement Audit

### Goal

Make it impossible for a Golden Journey to pass by manually performing
runtime transitions in its runner.

### Documentation

Update:

```text
docs/development_process.md
```

and create:

```text
docs/testing/
Golden_Journey_Platform_Integration_Testing_Contract_v1.0.md
```

### Testing Contract

Before request:

```text
business fixture seed allowed
identity/project/master seed allowed
external dependency preparation allowed
```

After request:

```text
Platform/API/browser only
poll/assert/restart allowed
runtime transition mutation forbidden
```

### Forbidden Golden-Journey Runner Operations

Examples:

```text
direct MultiStepEngine.schedule_next()
direct AgentExecution lifecycle UPDATE
direct RuntimeJob insertion
direct WorkItem/Claim/Assignment creation
direct Approval persistence
direct ResultDelivery ACK
direct WorkResult repository submit
direct WA evidence mutation
```

### Automated Audit

Add a repository quality script, conceptually:

```text
scripts/quality/run_golden_journey_transition_audit.py
```

It should check registered Golden Journey runners for:

```text
forbidden domain-repository imports
forbidden runtime transition calls
forbidden INSERT/UPDATE against runtime transition tables
```

SQL SELECT/assertion and post-run DELETE cleanup may remain allowed.

### Evidence Metadata

Golden Journey reports should expose:

```text
platform_integrated = true
runtime_transition_fixture = false
manual_domain_transition = false
installed_process_continuity = true
```

### Tests

Positive/negative audit fixtures.

### Exit

```text
testing contract committed
audit runs in Slice/Checkpoint/Full closure path
```

---

## GB2-CA00-S13 — Dependency Readiness Contract Foundation

### Goal

Separate configuration/provisioning/readiness from application use.

### Introduce

Canonical bounded projection:

```text
platform_dependency_readiness.v1
```

Logical fields:

```text
dependency_id
dependency_type
owner
required
configured
provisioned
reachable
authorized
ready
evidence_hash
checked_at
```

No secret values.

### Initial Dependency Types

```text
OPENBAO
OBJECT_STORAGE
MODEL_PROVIDER
```

### Aggregation

Provide a deterministic readiness aggregator:

```text
required dependency not ready
→ aggregate NOT_READY
```

The shared projection and aggregator normalize owner-produced readiness; they
do not replace owner-specific probes or become a second readiness engine.

Initial owner adapters SHALL reuse:

```text
OpenBao deployment/bootstrap readiness evidence
Object-storage lifecycle and authorization readiness
NeX-MO ProviderReadinessService / provider admission evidence
```

Do not duplicate provider preflight clients, OpenBao resolution logic,
object-storage lifecycle logic, or owner persistence in `nex_runtime`.

### Runtime Rule

```text
configured != ready
```

### Tests

```text
missing dependency
optional dependency
required dependency
authorization failure
hash stability
secret redaction
```

### Exit

```text
shared dependency readiness vocabulary exists
```

---

## GB2-CA00-S14 — OpenBao Provisioning / Runtime Resolution Separation

### Goal

Make OpenBao deployment preparation canonical rather than known only to P8
Demo acceptance.

### Preserve Product Runtime

Existing:

```text
OpenBaoSecretResolver
production_container_bootstrap
```

remain secret-consumption components.

### Canonical Deployment Side

Promote/reuse existing staging/provisioning functions for:

```text
initialize/unseal as applicable
AppRole/policy configuration
owner secret path preparation
Transit/signing trust preparation where required
credential file materialization
readiness evidence
```

### Separation

```text
deployment/bootstrap
→ provisions OpenBao environment

container bootstrap
→ resolves owner secrets

business runtime
→ never provisions OpenBao
```

### P8-DEMO

P8-DEMO deployment script becomes wrapper/consumer of canonical OpenBao
provisioning utilities.

### Protected Acceptance

```text
provision
→ resolve owner secret
→ restart
→ resolve again
→ no raw secret in evidence
```

### Gate

Production bootstrap changes require risk-escalated Checkpoint Gate.

---

## GB2-CA00-S15 — RustFS / S3 Object-Storage Provisioning and Readiness

### Goal

Move bucket/IAM preparation out of Golden Journey-specific acceptance logic.

### Reuse

Existing:

```text
object_storage.py
object_storage_lifecycle.bootstrap_private_bucket
IAM provisioning components
AE private object-store client
```

### Canonical Deployment Operation

For each declared owner:

```text
ensure bucket
ensure owner identity/policy
verify owner access
verify cross-owner isolation
produce readiness evidence
```

Initial owner set remains source-backed:

```text
AE private storage
CX private storage
```

Do not add WA byte storage.

### Runtime Readiness

AE S3 private storage is READY only if:

```text
configuration valid
credentials resolved
bucket reachable
authorization accepted
```

### P8-DEMO

`_provision_demo_object_storage()` should be reduced to a wrapper around the
canonical operation or removed from ownership of the logic.

### Protected Acceptance

```text
bucket bootstrap
IAM/policy
owner head_bucket
cross-bucket denied
restart recovery
no secrets in evidence
```

### Exit

```text
Object storage provisioning is deployment-owned
application uses admitted storage only
```

---

## GB2-CA00-S16 — Model Provider Admission and Readiness

### Goal

Make live model readiness a declared Platform dependency.

### Current P8-DEMO Pattern

Demo preflight validates:

```text
generation
embedding
reranking
```

### Target

Canonical provider readiness should be owned by the Platform/provider boundary,
not Golden Journey runner.

### Profile Requirements

For GB2-CA00 current continuity:

```text
generation = REQUIRED
embedding  = profile-dependent
reranking  = profile-dependent
```

### Readiness Must Prove

```text
configured
authorized
model identity admitted
bounded request succeeds
timeout policy valid
response observed
```

### No Evidence Leakage

Do not store:

```text
provider API key
raw provider endpoint if policy forbids
prompt content
raw response
```

### Runtime Admission

`NEX_MO_PROVIDER_MODE=live` alone is insufficient.

Required provider readiness must pass before live semantic planning is
considered ready.

### P8-DEMO

Existing live preflight becomes wrapper/reuse of canonical provider readiness.

### Checkpoint Gate #3

Run after S16.

### Exit — CA00-DEPENDENCY-01

```text
OpenBao canonical readiness
Object storage canonical readiness
generation provider canonical readiness
all separable from Golden Journey runner
```

---

# 14. Band D — Canonicalization, Installed Acceptance, and Freeze

## GB2-CA00-S17 — Demo-to-Product Dependency Closure

### Goal

Prove canonical product runtime no longer depends on Demo modules while keeping
historical Demo compatibility.

### Product Runtime Negative Audit

Canonical product paths must not import:

```text
p8_demo_semantic_activation
p8_demo_runtime_composition
demo_fixture
demo_processes
```

except from explicitly marked Demo wrappers/tests.

### Required Regression

Run existing relevant P8-DEMO regressions:

```text
S10 installed domain
S10B installed runtime
S10C result closure
S11 Golden A journey
```

They should now flow through canonical components.

### Required Result

```text
historical P8-DEMO semantics preserved
demo-owned orchestration reduced
current Platform components authoritative
```

### Full Gate #2

Run Full Gate because this is the compatibility closure for the promoted
runtime.

### Exit

```text
no canonical product import of demo runtime/fixture
P8-DEMO compatibility PASS
Full Gate PASS
```

---

## GB2-CA00-S18 — Installed Current-Platform Continuity E2E

### Goal

Prove the main problem is actually closed.

Use:

```text
current Platform runtime manifest
current deployment artifact catalog
current packaged entrypoints
canonical dependency readiness
```

Do not use:

```text
P8-DEMO process manifest
manual component composition in runner
runtime transition fixture
```

### Journey Choice

Use Golden A as a continuity probe because it already exercises:

```text
live semantic planning
COMPILED scheduling
AE worker
Approval
WC delivery
Resume
NSL controlled WRITE
EOS BusinessOperation
EOS publication
AgentResult finalization
WORKSPACE_RESULT ACK
```

The objective is not to revalidate Golden A business design.

The objective is:

```text
installed current Platform continuity
```

### Setup Allowed

Before request:

```text
test tenant
users
Project/account business master
Golden A business source fixture
service principals
canonical dependency provisioning
canonical capability/Skill registration
```

### After Request — Forbidden

The runner SHALL NOT:

```text
schedule_next
create RuntimeJob
create WorkItem/Claim
mutate Approval
ACK ResultDelivery
submit WorkResult through repository
advance AgentExecution with SQL
```

### Required Path

```text
browser/API request
→ semantic admission
→ COMPILED
→ automatic schedule_next
→ current AE Agent Runtime worker
→ NSL approval wait
→ WC approval path
→ current WC event-delivery worker
→ RESUME_EXECUTION
→ controlled WRITE
→ EOS transaction
→ current EOS outbox publisher
→ result verification/finalization
→ WORKSPACE_RESULT ACK
→ user-visible result
```

Where current P9 notifier/readiness is enabled:

```text
→ WA post-work admission
```

may also be verified as additive current-platform evidence.

### Installed Environment

Prefer the full current topology:

```text
9 artifacts
20 processes
```

with actual current PostgreSQL databases and signed trust.

### Required Assertions

```text
platform_integrated = true
runtime_transition_fixture = false
manual_domain_transition = false
installed_process_continuity = true

one semantic transaction
one AgentResult
one required ResultDelivery ACK
no duplicate business operation
no duplicate result
no pending runtime transition after completion
```

### Protected Dependencies

Use canonical S14-S16 preparation.

### Zero Residue

After acceptance:

```text
test-owned DB residue = 0
temporary service trust = 0
temporary dependency fixture residue = 0
containers/processes cleaned as declared
```

### Exit

```text
current Platform can execute Golden A continuity without Demo orchestration
```

---

## GB2-CA00-S19 — Fail-Closed / Restart / Hidden-Gap Acceptance

### Goal

Prove the Platform does not merely work in the happy path.

### Negative Scenarios

At minimum:

```text
N01 AE runtime worker unavailable
→ work does not falsely complete

N02 WC delivery worker unavailable
→ approval/result event remains pending
→ no false resume

N03 EOS publisher unavailable
→ pending outbox remains recoverable
→ no duplicate transaction

N04 required OpenBao readiness absent
→ installed startup/readiness blocked

N05 required object storage not admitted
→ Artifact/storage-dependent path blocked

N06 generation provider readiness absent
→ required live planning blocked

N07 unknown required domain activator
→ fail closed

N08 stale/duplicate worker restart
→ no duplicate settlement

N09 Golden Journey audit detects a deliberately forbidden transition fixture
→ test fails
```

### Restart Scenarios

At minimum:

```text
restart AE worker during pending work
restart WC worker with pending delivery
restart EOS publisher with pending outbox
```

and show durable recovery.

### Exit

```text
missing installed link is visible as failure
no hidden smoke bypass remains
```

---

## GB2-CA00-S20 — Repository Closure / Final As-Built / Golden B v2 Entry

### Goal

Freeze GB2-CA00 and authorize Golden B v2 business work.

### Create

```text
docs/transition/GB2/
GB2_CA00_Final_AsBuilt_and_Golden_B_v2_Entry_Handoff_v1.0.md
```

Update relevant transition README/index.

### Record

```text
exact commit/tree
9-artifact / 20-process topology
canonical worker entrypoints
generic AE runtime factory
domain activator registry
Golden A product registration
testing contract
dependency readiness contracts
protected installed E2E evidence
negative/restart evidence
P8-DEMO compatibility evidence
coverage
Full Gate
zero residue
```

### Final Repository Full Gate

Run:

```text
scripts/quality/run_quality_gate.sh
```

and all GB2-CA00 protected acceptance.

Required:

```text
exit code = 0
Statement >= 96%
Branch    >= 94%
contracts PASS
AE Web PASS
P8-DEMO compatibility PASS
current Platform E2E PASS
zero residue PASS
git diff --check PASS
```

Compare with entry baseline:

```text
18,268 passed
131 protected skips
96.01 / 95.22
```

Any delta must be explained.

### Final Decision

Only after this Slice:

```text
GB2-CA00 = CLOSED
Golden B v2 implementation = AUTHORIZED
```

---

# 15. Gate Cadence

Recommended cadence:

```text
S01  docs-only
S02  shared runtime capability taxonomy
S03  generic AE composition
S04  P8 Demo rebind
S05  AE worker promotion
     → Checkpoint Gate #1

S06  WC worker promotion
S07  EOS publisher promotion
S08  current topology closure
     → Full Gate #1

S09  activator registry
S10  Golden A product activator
     → Checkpoint Gate #2
S11  capability/Skill registration boundary

S12  testing contract
S13  dependency readiness core
S14  OpenBao
S15  Object storage
S16  provider readiness
     → Checkpoint Gate #3

S17  Demo-to-product compatibility closure
     → Full Gate #2

S18  installed current-Platform E2E
S19  fail-closed/restart acceptance
S20  final closure
     → Final Full Gate
```

Run an earlier Checkpoint/Full Gate whenever a Slice changes:

```text
_shared runtime
production bootstrap
auth/trust
multiple services
deployment artifact catalog
quality infrastructure
```

---

# 16. Protected Acceptance Matrix

| ID | Acceptance |
|---|---|
| CA00-E2E-01 | AE canonical worker claims and settles real runtime work |
| CA00-E2E-02 | WC canonical worker delivers one pending event exactly once |
| CA00-E2E-03 | EOS canonical publisher drains one outbox item exactly once |
| CA00-E2E-04 | Golden A Demo still works through canonical factory |
| CA00-E2E-05 | Semantic admission works without direct demo activator import |
| CA00-E2E-06 | Capability and Skill identities remain distinct |
| CA00-E2E-07 | Golden Journey runner has zero runtime-transition fixture |
| CA00-E2E-08 | OpenBao provision/readiness survives restart |
| CA00-E2E-09 | Object-storage owner provisioning/isolation PASS |
| CA00-E2E-10 | Generation provider readiness PASS |
| CA00-E2E-11 | Current Platform 9-artifact/20-process continuity PASS |
| CA00-E2E-12 | Missing AE worker fails visibly |
| CA00-E2E-13 | Missing WC worker cannot falsely resume |
| CA00-E2E-14 | Missing EOS publisher preserves recoverable outbox |
| CA00-E2E-15 | Worker restarts do not duplicate business effects |
| CA00-E2E-16 | Zero owned residue |

---

# 17. Smoke / Golden Journey SQL Rule

Golden Journey acceptance may use SQL for:

```text
pre-request authoritative business fixture seed
read-only assertion/query
post-run cleanup
```

It may not use SQL for the runtime transition being claimed.

Forbidden transition tables include, at minimum, writes to:

```text
ae_agent_execution
ae_runtime_job
ae_executable_step
ae_wait_registration
ae_agent_result
ae_result_delivery

wc_work_item
wc_claim
wc_assignment
wc_work_result
wc_approval_work_item
wc_approval_decision

eos_business_operation
transaction/outbox state required by the claimed journey

wa_work_evidence
wa_work_asset
wa_work_asset_evidence
```

Exact table inventory should be source-derived in S12.

---

# 18. Process Promotion Definition of Done

A worker is not promoted merely because:

```text
module imports
--check passes
heartbeat starts
```

Promotion requires:

```text
canonical current manifest presence
canonical artifact binding
canonical packaged entrypoint
truthful capability metadata
actual work-loop execution
persistence dependency
heartbeat
restart
idempotent recovery
protected acceptance
```

---

# 19. Generic Runtime Factory Definition of Done

The generic AE factory is complete only when:

```text
P8 Demo uses it
current AE worker uses it
it contains no Demo fixture path
it contains no Golden A business constant
it owns dispatcher/worker/engine composition
executor/business profiles are injected
result closure remains generic
```

---

# 20. Domain Activator Registry Definition of Done

Registry is complete only when:

```text
semantic admission core imports no demo activation module
Golden A is registered through canonical product builder
duplicate registration fails
unknown required activation fails
capability identity != Skill identity
Golden B can later add an activator without editing semantic admission core
```

---

# 21. Testing Contract Definition of Done

Testing policy is complete only when:

```text
documented rule exists
automated audit exists
negative fixture proves audit catches forbidden transition
Golden Journey reports declare platform-integrated metadata
current installed E2E passes without transition fixture
```

---

# 22. Dependency Readiness Definition of Done

Dependency readiness is complete only when:

```text
Provisioning and application runtime are separate.

OpenBao:
  deployment provision
  runtime secret resolution

Object Storage:
  deployment bucket/IAM provision
  runtime object-store use

Model Provider:
  deployment/runtime admission preflight
  semantic planning use

All:
  explicit readiness
  no secrets in evidence
  fail closed when required dependency is absent
```

---

# 23. P8-DEMO Compatibility Policy

P8-DEMO remains valuable historical acceptance.

Do not delete it.

Target relationship:

```text
P8 Demo wrapper/config
        ↓
Canonical Platform runtime
```

not:

```text
Canonical Platform runtime
        ↓
P8 Demo module
```

Historical paths may remain for reproducibility, but product modules may not
depend on Demo-only orchestration.

---

# 24. Branch / Merge Guidance

GB2-CA00 is cross-cutting.

A short-lived implementation branch is acceptable, but the source of truth
remains:

```text
transition/p4-agent-runtime-foundation
```

If a separate branch is used:

```text
branch from current HEAD
preserve per-Slice commits
merge no later than major checkpoint
rerun affected current-branch Gate after merge
```

Do not allow a second long-lived Demo-only runtime line to emerge.

---

# 25. Recommended Commit Themes

Illustrative:

```text
docs(gb2): freeze platform internalization inventory

refactor(ae): extract installed runtime composition

refactor(demo): use canonical AE runtime factory

feat(runtime): promote AE agent worker

feat(wc): promote event delivery worker

feat(eos): promote outbox publisher

feat(ae): add domain intent activator registry

refactor(ae): productize Golden A activation

test(platform): enforce golden journey transition boundary

feat(runtime): add dependency readiness contract

refactor(deploy): promote openbao and object storage readiness

feat(mo): promote provider readiness

test(platform): prove installed current-platform continuity

docs(gb2): freeze GB2-CA00 handoff
```

Exact messages are implementation choice.

---

# 26. Stop Conditions

Stop and return to architecture review if any Slice tries to:

```text
create a second Agent Runtime worker framework
create a second dispatcher
replace MultiStepEngine
add a new queue for existing flow
create a broker solely for promotion
change AgentExecution trigger semantics
change approval authority
change ResultDelivery completion semantics
put Golden A fixture parsing into generic runtime
allow current Platform to depend on p8_demo runtime
make business request provision RustFS/OpenBao/IAM
```

---

# 27. GB2-CA00 Final Definition of Done

All must be true:

```text
[ ] 9 current artifacts preserved
[ ] 20 current processes admitted
[ ] AE Agent Runtime worker first-class
[ ] WC delivery worker first-class
[ ] EOS outbox publisher first-class

[ ] generic AE installed runtime factory exists
[ ] P8-DEMO uses generic factory
[ ] canonical runtime does not import demo composition

[ ] DomainIntentActivatorRegistry exists
[ ] semantic admission does not import p8_demo_semantic_activation
[ ] Golden A registered as product domain profile
[ ] capability != Skill invariant preserved
[ ] product capability existence is not fixture-defined

[ ] Golden Journey testing contract committed
[ ] runtime transition fixture audit automated
[ ] forbidden transition negative test PASS

[ ] OpenBao provisioning/readiness canonical
[ ] RustFS/S3 provisioning/readiness canonical
[ ] generation provider readiness canonical
[ ] configured != ready enforced

[ ] P8-DEMO compatibility PASS
[ ] current Platform installed continuity PASS
[ ] fail-closed/restart acceptance PASS
[ ] zero owned residue PASS

[ ] Repository Full Gate PASS
[ ] Statement >= 96%
[ ] Branch >= 94%
[ ] git diff --check PASS

[ ] GB2-CA00 Final As-Built frozen
[ ] Golden B v2 implementation explicitly authorized
```

---

# 28. Handoff to Golden B v2

After GB2-CA00 closes, Golden B v2 should not need to solve Platform
installation again.

Golden B v2 scope becomes:

```text
manufacturing evidence source
Manufacturing business capability
PA claimed-work planning profile
manufacturing READ path
Manufacturing Readiness Artifact
IA → WC → PA business journey
WA evidence verification
business negative cases
```

It should reuse:

```text
current AE worker
current WC worker
current EOS publisher
generic AE runtime composition
domain activator registry
Golden Journey testing contract
canonical dependency readiness
```

---

# 29. Final Plan Position

The implementation order is intentionally:

```text
inventory
→ genericize
→ promote workers
→ generalize domain activation
→ harden testing contract
→ promote dependency readiness
→ prove current installed continuity
→ freeze
```

rather than:

```text
Golden B business coding
→ discover missing runtime links
→ patch Smoke
→ patch Demo
→ repeat
```

The final criterion remains:

> **Smoke should prove that the Platform works; Smoke must not be the thing
> that makes the Platform work.**
