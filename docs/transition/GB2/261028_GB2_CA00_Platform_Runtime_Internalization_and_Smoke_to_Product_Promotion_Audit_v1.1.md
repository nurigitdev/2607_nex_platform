# GB2-CA00 — Platform Runtime Internalization & Smoke-to-Product Promotion
# Source Audit and Pre-Architecture Decision v1.1

**Status:** PRE-IMPLEMENTATION / SOURCE-BACKED GAP CLOSURE PLAN / v1.1 / GB2-CA00A RECONCILED
**Program:** NeX Platform v2.1
**Predecessor:** P9 Foundation CLOSED / Golden B v2 Design Draft v0.1
**Purpose:** Golden B v2 착수 전 Platform Runtime 내재화 및 Smoke-to-Product 승격
**Repository:** `nurigitdev/2607_nex_platform`
**Branch:** `transition/p4-agent-runtime-foundation`
**Observed HEAD:** `a066dcffa4097cb0d33daf5e749e9e24c7481679`
**Observed HEAD Message:** `docs(wa): freeze P9 privacy corrective closure`
**Date:** 2026-10-28

---

# 1. Executive Summary

P4~P9 동안 NeX Platform은 다음 핵심 capability를 단계적으로 구현했다.

```text
Semantic Planning
Agent Runtime
WC Delegation / Claim
Approval / Resume
NSL Controlled WRITE
EOS BusinessOperation
Result Publication
WorkEvidence / WorkAsset
```

각 capability는 단위/통합/Protected Smoke/E2E에서 높은 수준으로 검증되었다.

그러나 P8-DEMO를 실제 별도 branch에서 설치형 release로 준비하는 과정에서 다음의 구조적 문제가 드러났다.

```text
Implemented Capability
!=
Installed Product Runtime
```

즉, source에는 dispatcher, worker, engine, approval adapter, controlled WRITE,
result closer 등이 각각 존재했지만, 이들을 **제품 실행환경에서 하나의 정상 runtime으로 조립하는
canonical Platform composition**이 없는 경우가 있었다.

이 간극은 Smoke/Deployment test가 다음 방식으로 가려줄 수 있었다.

```text
hard-coded parameter
demo-only fixture
direct repository call
direct SQL mutation
test-side component composition
manual scheduling / state advancement
```

따라서 테스트 결과는 PASS이지만 실제 설치된 Platform process에서는 동일한 흐름이
자동으로 이어지지 않는 상태가 가능했다.

P8-DEMO는 이 문제들을 상당수 실제 설치형 topology에서 발견하고 보완하였다.

하지만 현재 repository를 다시 확인한 결과, 다음 일부가 아직 **Demo-specific layer에 남아 있다.**

```text
P8-DEMO installed workers
P8-DEMO runtime composition
P8-DEMO semantic/domain activation
P8-DEMO fixture-oriented capability activation
P8-DEMO external dependency bootstrap
```

Golden B v2를 시작하기 전에 이 경계를 Platform standard로 승격해야 한다.

본 문서는 다음 5개 작업을 GB2-CA00의 필수 범위로 정의한다.

```text
1. AE Runtime / WC Delivery / EOS Outbox worker를 current Platform process topology로 승격
2. p8_demo_runtime_composition을 generic installed runtime factory로 추출
3. p8_demo_semantic_activation의 fixture 기반 domain activation을 registry 기반으로 일반화
4. Smoke runner가 runtime transition을 만드는 것을 금지하는 testing contract 추가
5. RustFS/OpenBao/provider bootstrap을 deployment readiness contract로 명확히 분리
```

---


# 1A. Platform Worker Promotion Reference Principle

P9에서 구현한 `nex-wa-evidence-consumer`는 이미 current Platform topology에
정식으로 포함된 first-class background worker이다.

현재 source 기준으로 NeX-WA worker는:

```text
current process manifest 등록
deployment artifact binding
canonical packaged entrypoint
job_claiming capability
owner-local PostgreSQL
worker heartbeat
fenced stale-job recovery
restart-safe idempotency
installed runtime acceptance
```

을 갖춘다.

따라서 GB2-CA00에서 NeX-WA worker는 **승격 대상이 아니라 reference
implementation**으로 취급한다.

GB2-CA00의 핵심 목표는 다음과 같이 정의한다.

> **P9에서 NeX-WA worker에 적용한 수준의 first-class runtime
> integration을, P8-DEMO에서만 설치형으로 존재했던 AE/WC/EOS domain
> workers에도 동일한 수준으로 승격하여 Platform에 내재화한다.**

즉 current P9 Platform의 `17 processes`에는 이미:

```text
nex-wa-evidence-consumer
```

가 포함되어 있으며, GB2-CA00은 다음 3개만 추가한다.

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

따라서 목표 topology는:

```text
Current P9 Platform = 17 processes
  [includes nex-wa-evidence-consumer]

GB2-CA00 promotion targets = +3 processes

Target current Platform = 20 processes
```

이다.

중요한 점은 네 worker의 내부 처리 알고리즘을 동일하게 만드는 것이 아니다.

```text
WA  → JobQueue evidence consumption
AE  → RuntimeJob / dispatcher assignment
WC  → event/result delivery
EOS → outbox publication
```

각 owner-domain의 실행 모델은 유지한다.

공통으로 맞춰야 하는 것은 **first-class Platform runtime integration
수준**이다.

```text
process identity
artifact binding
packaged entrypoint
truthful work capability
owner DB dependency
heartbeat
readiness
graceful shutdown
restart/recovery
protected installed acceptance
```

이 기준을 `GB2-INV-PLATFORM-00`으로 둔다.

```text
GB2-INV-PLATFORM-00

NeX-WA evidence consumer is the current reference level for first-class
background-worker integration.

AE Runtime, WC Delivery, and EOS Outbox workers SHALL be promoted to the same
Platform integration level while preserving each owner's existing execution
semantics.
```

---

# 2. Core Problem Statement

현재까지의 개발 방식은 capability-first 접근이었다.

```text
Capability 구현
→ unit test
→ integration test
→ protected smoke
→ phase closure
```

이 방식은 기능 자체의 정확성을 검증하는 데에는 매우 효과적이었다.

그러나 다음 질문은 별개의 문제다.

> "이 capability가 실제 설치된 Platform process가 기동되었을 때 자동으로 연결되는가?"

예:

```text
Semantic Candidate COMPILED
        ↓
누가 schedule_next()를 호출하는가?

RuntimeJob READY
        ↓
실제 설치된 worker가 claim하는가?

Approval APPROVED
        ↓
누가 RESUME_EXECUTION을 만들어 주는가?

Controlled WRITE 완료
        ↓
누가 RESULT_VERIFY / FINALIZE를 수행하는가?

AgentResult 생성
        ↓
누가 ResultDelivery를 publish/ACK 하는가?
```

Smoke가 위 중간 단계를 직접 수행한다면 기능은 PASS할 수 있다.

하지만 Product Runtime은 끊어진 상태일 수 있다.

따라서 앞으로는 다음을 별도로 증명해야 한다.

```text
Capability Correctness
+
Product Composition Correctness
+
Installed Runtime Reachability
```

---

# 3. New Platform Principle

본 Gate는 다음 원칙을 freeze한다.

```text
GB2-INV-PLATFORM-01

A capability is not considered Platform-integrated merely because it can be
demonstrated by unit, integration, smoke, or deployment code.

Every runtime transition required after a business request is accepted SHALL
be reachable through an installed Platform process and an admitted runtime/API
contract.
```

한국어 의미:

> Smoke가 기능을 호출할 수 있다는 사실과 Platform이 스스로 그 기능을 수행할 수 있다는
> 사실을 동일하게 취급하지 않는다.

---

# 4. Fixture Principle

Fixture 사용 자체는 금지하지 않는다.

허용:

```text
Business Source Fixture
Project seed
User/Subject seed
Agent registration
Manufacturing status seed
Account master seed
Test external system response
```

금지:

```text
Runtime Transition Fixture
pre-created WorkItem
pre-created Claim
pre-created AgentExecution
pre-approved Approval
pre-created AgentResult
pre-ACKed ResultDelivery
pre-created WorkResult
pre-created WA evidence
```

Invariant:

```text
GB2-INV-PLATFORM-02

Business fixtures MAY establish authoritative source facts.

Fixtures SHALL NOT pre-create or directly advance platform runtime transition
state required by the Golden Journey.
```

---

# 5. Current Source-Backed Findings

## 5.1 Current Platform Process Topology

Current Platform manifest:

```text
services/_shared/nex_runtime/process_manifest.py
```

defines:

```text
CURRENT_BACKGROUND_PROCESS_IDS
=
historical background processes
+
nex-wa-evidence-consumer
```

Current Platform topology includes:

```text
AE artifact render worker
AE retention daemon
AG remediation worker
AG dispatch daemon
CX async generation worker
CX ingestion worker
CX remediation worker
WA evidence consumer
```

However the following P8-DEMO processes are not in the current Platform process manifest:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

## 5.2 P8-DEMO Process Topology

P8-DEMO defines:

```text
services/_shared/nex_runtime/demo_processes.py
```

with installed:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

and embedded:

```text
nex-ae-agent-runtime-dispatcher
```

This means P8-DEMO successfully proved these processes as installed workers,
but the same worker set has not yet become part of the canonical current Platform manifest.

---

# 6. Finding #1 — Domain Workers Are Still Demo-Promoted, Not Platform-Promoted

## 6.1 Current State

P8-DEMO installed:

```text
AE Agent Runtime worker
WC event-delivery worker
EOS outbox publisher
```

and verified:

```text
heartbeat
restart
signed trust
actual PostgreSQL
domain claiming
```

Current Platform topology does not list those workers.

Therefore:

```text
P8-DEMO runtime topology
>
current Platform domain-worker topology
```

for these specific processes.

## 6.2 Risk

Golden B v2 requires:

```text
DELEGATE_WORK
→ WC
→ Claim
→ AE child AgentExecution
→ Worker claim
→ Result
→ WC delivery
→ parent resume
```

If current Platform topology lacks the required workers, a demo script may again
need to manually run these functions.

That recreates the original problem.

## 6.3 Target

Promote as current Platform first-class processes:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

The AE dispatcher remains:

```text
embedded component hosted by AE runtime worker
```

unless a separate source-backed reason justifies an independent dispatcher process.

## 6.4 Required Platform Artifacts

Current:

```text
nex-ae-runtime
nex-wc-runtime
nex-eos-runtime
```

already exist.

Therefore new OCI artifacts are not required.

What is required:

```text
current process manifest binding
current deployment artifact binding
packaged entrypoint
worker capability classification
worker database env
worker heartbeat
restart contract
dependencies
readiness
```

---

# 7. Finding #2 — Generic P6/P8 Installed Runtime Composition Is Still Demo-Specific

## 7.1 Current Source

Current installed composition exists in:

```text
services/nex-ae-api/nex_ae_api/p8_demo_runtime_composition.py
```

It correctly composes existing components:

```text
SqlAlchemyRuntimeJobQueue
SqlAlchemyMultiStepEngine
default_p6_executor_registry
P5StepExecutionWorker
SqlAlchemyNslApprovalResumeSource
SqlAlchemyAgentRuntimeDispatcher
run_bounded_agent_runtime_worker
SqlAlchemyInstalledIaResultCloser
WorkspaceResultPublisher
```

This is architecturally valuable.

However it also directly creates:

```text
P8DemoControlledSkillRuntime
```

and consumes:

```text
NEX_AE_DEMO_NSL_BUNDLE_MANIFEST
NEX_AE_DEMO_NSL_WHEEL
NEX_AE_DEMO_PLATFORM_LOCK
NEX_AE_DEMO_NSL_SKILL_ROOT
NEX_AE_DEMO_FIXTURE
NEX_AE_DEMO_BASE_FIXTURE
```

It even has historical local defaults such as a Golden A example Skill root.

## 7.2 Problem

Generic runtime composition and Golden A demo configuration are mixed.

Current conceptual state:

```text
Installed Runtime Factory
+
Golden A Demo Skill
+
Golden A Demo Fixture
+
Demo Package Paths
=
one composition module
```

This prevents reuse for Golden B without another demo-specific composition.

## 7.3 Target

Extract generic:

```text
InstalledAgentRuntimeComposition
```

conceptually into a canonical module such as:

```text
nex_ae_api/installed_runtime.py
or
nex_ae_api/runtime_composition.py
```

The exact filename is implementation scope.

The generic factory should compose:

```text
RuntimeJobQueue
MultiStepEngine
AgentRuntimeDispatcher
AgentRuntimeAssignmentSource
AgentRuntimeWorker
ExecutorRegistry
ContinuationSource
ResultCloser
ResultPublisher
optional post-completion notifier
```

It should receive scenario/domain execution dependencies through interfaces.

It must not know:

```text
Golden A
voucher
P8 demo fixture
local Skill example path
Chairman demo
```

---

# 8. Scenario-Specific Runtime Adapter

After generic extraction:

```text
p8_demo_runtime_composition.py
```

should become a thin configuration adapter.

Conceptually:

```text
Golden A Demo
    │
    ├─ admitted Skill package
    ├─ Golden A fixture/config
    └─ local skill handlers
        │
        ▼
Generic InstalledAgentRuntimeComposition
```

Golden B later becomes:

```text
Golden B Manufacturing profile
    │
    ├─ manufacturing domain activator
    ├─ manufacturing READ capability
    └─ artifact/result handler
        │
        ▼
Generic InstalledAgentRuntimeComposition
```

No second dispatcher/worker/engine should be created.

---

# 9. Finding #3 — Semantic Domain Activation Is Still Demo Fixture-Coupled

## 9.1 Current Source

Product semantic admission:

```text
services/nex-ae-api/nex_ae_api/semantic_candidate_admission.py
```

currently imports:

```text
p8_demo_semantic_activation.build_p8_demo_intent_activators
```

The builder requires:

```text
NEX_AE_DEMO_GOLDEN_A_ADMISSION_ENABLED
NEX_AE_DEMO_FIXTURE
NEX_AE_DEMO_BASE_FIXTURE
```

and returns:

```text
{ FINANCE.CREATE_VOUCHER_DRAFT : Golden A demo activator }
```

## 9.2 What Is Already Correct

The planning pipeline itself is general.

It supports:

```text
INTENT
CONTEXT
PLAN
Capability Snapshot
Plan Validation
Executable Plan
AgentExecution
```

and when:

```text
mode = required
status = COMPILED
```

it now calls:

```text
scheduler.schedule_next(...)
```

Therefore COMPILED→RuntimeJob scheduling is already productized.

## 9.3 Remaining Gap

Domain-specific activation remains:

```text
Product Semantic Admission
→ P8 Demo Activator
→ Demo Fixture
```

This is not acceptable as the long-term domain extension model.

---

# 10. Target Domain Intent Activator Registry

Introduce a general concept:

```text
DomainIntentActivatorRegistry
```

Responsibilities:

```text
register activator by business capability
lookup exact capability
fail closed on duplicate registration
fail closed on unknown required activation
provide deterministic domain binding
preserve candidate hash / activation hash
```

Exact implementation may differ.

---

# 11. Capability vs Skill Invariant

Golden A already demonstrates the correct semantic distinction.

```text
Business Capability
FINANCE.CREATE_VOUCHER_DRAFT

Execution Skill
FINANCE.VOUCHER_DRAFT_CREATE
```

Freeze:

```text
GB2-INV-PLATFORM-03

Business Capability identity SHALL remain distinct from execution Skill identity.
```

Golden B must follow the same rule.

Example only:

```text
Capability:
MANUFACTURING.ASSESS_DELIVERY_READINESS

Skill / Tool:
MANUFACTURING.READINESS_READ
```

Names are not frozen by this document.

---

# 12. Domain Registration Sources

A general registry may receive registrations from:

```text
versioned code registration
deployment package manifest
capability registry seed
admin/governance admission
```

The initial implementation should use the smallest current-compatible method.

But it must not depend on:

```text
scripts/smoke/data/...
scripts/deployment/data/...
```

to define production business capability existence.

---

# 13. Finding #4 — Smoke Can Still Create or Advance Runtime State

Historical smoke/deployment scripts legitimately:

```text
seed fixtures
query databases
clean up test data
```

However historical smoke also performed operations such as:

```text
direct schedule_next()
direct repository save()
direct component construction()
direct approval delivery invocation()
direct SQL state update()
```

depending on the phase.

P8-DEMO reduced several of these gaps by installing real processes.

But the testing contract itself does not yet universally prohibit this pattern.

---

# 14. Smoke Testing Contract

## 14.1 Allowed Before Journey Start

Smoke may:

```text
create test tenant
create Project/master data
create Human/Agent fixture
seed external business source facts
prepare test credentials
prepare external dependency resources
start installed Platform processes
```

## 14.2 Allowed After Journey Start

After the business request is submitted, Smoke may only:

```text
call admitted Platform API
use browser/UI
wait/poll
read state
assert state
inject declared infrastructure faults
restart installed processes
collect sanitized evidence
clean test-owned data after journey completion
```

## 14.3 Forbidden After Journey Start

Smoke SHALL NOT:

```text
INSERT WorkItem
INSERT Claim
INSERT Assignment
INSERT AgentExecution
UPDATE AgentExecution lifecycle
INSERT Approval decision
UPDATE approval state
schedule RuntimeJob directly
ACK ResultDelivery directly
INSERT WorkResult
INSERT WorkEvidence
manually call internal domain transition functions in lieu of installed runtime
```

Exception:

A narrowly scoped component test may do these operations when explicitly testing
that component, but such a test cannot be used as evidence of Platform-integrated
Golden Journey acceptance.

---

# 15. Golden Journey Acceptance Rule

Freeze:

```text
GB2-INV-PLATFORM-04

After the user/business request enters the Platform, every business/runtime
transition required for Golden Journey success SHALL be caused by an installed
Platform process or an admitted Platform API.
```

Therefore:

```text
component test PASS
!=
Golden Journey Platform PASS
```

---

# 16. Testing Evidence Classification

Introduce evidence classes:

```text
UNIT
COMPONENT
INTEGRATION
PROTECTED_COMPONENT
INSTALLED_PLATFORM
GOLDEN_JOURNEY
```

Only:

```text
INSTALLED_PLATFORM
GOLDEN_JOURNEY
```

may claim product runtime continuity.

A test report should explicitly declare:

```text
transition_fixture_used = false
direct_runtime_sql_used = false
manual_domain_transition_used = false
installed_process_path = true
```

---

# 17. Static / Runtime Audit for Smoke Boundary

Add a test/audit that scans Golden Journey runners for prohibited patterns.

Potential checks:

```text
direct import of SqlAlchemy domain repositories
direct import of MultiStepEngine in Golden Journey runner
direct schedule_next()
direct transition SQL against runtime tables
direct approval decision repository
direct ResultDelivery update
direct WorkResult repository mutation
```

This audit does not need to ban SQL entirely.

Allowed SQL:

```text
setup seed
assertion query
cleanup
```

The rule is semantic:

> SQL may prepare/observe/clean the test environment, but must not perform the
> runtime transition being claimed as Platform behavior.

---

# 18. Finding #5 — External Dependency Bootstrap Is Demo-Acceptance Oriented

P8-DEMO correctly discovered that container startup alone was insufficient.

Examples:

```text
RustFS container running
!=
AE private object storage ready
```

Required additional actions included:

```text
bucket creation
owner IAM provisioning
policy registration
TLS readiness
tenant/owner isolation validation
```

P8-DEMO performs this in:

```text
scripts/deployment/run_p8_demo_s10_installed_domain_acceptance.py
```

with `_provision_demo_object_storage(...)`.

It creates private buckets and owner identities/policies for current demo owners.

---

# 19. Current Product Runtime Pieces

Platform already has production-quality components for:

```text
OpenBao secret resolution
production container bootstrap
S3-compatible object-storage client
object-storage settings validation
private object-store use
service-token verification
provider client configuration
```

Examples:

```text
nex_runtime/openbao_secret_resolver.py
nex_runtime/production_container_bootstrap.py
nex_runtime/object_storage.py
nex_ae_api/private_object_store.py
```

The gap is not client capability.

The gap is:

```text
external dependency provisioning/readiness contract
```

---

# 20. Target Deployment Readiness Separation

Deployment lifecycle should explicitly distinguish:

```text
Provision
Configure
Admit
Start
Ready
Run
```

Example:

```text
OpenBao
  provision trust/auth policy
  → materialize owner secret refs
  → readiness
  → service start

RustFS
  provision bucket
  → provision owner identity/policy
  → head_bucket/readiness
  → service start

MO Provider
  configure endpoint/model/auth
  → live capability preflight
  → readiness
  → semantic planning enabled
```

---

# 21. Deployment Readiness Contract

Define a canonical projection such as:

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

Potential dependencies:

```text
openbao
object-storage:ae
object-storage:cx
provider:generation
provider:embedding
provider:reranking
```

Exact schema is implementation scope.

---

# 22. Readiness Must Be Used by Runtime Admission

A critical rule:

```text
configured env
!=
runtime ready
```

Examples:

```text
NEX_AE_PRIVATE_STORAGE_MODE=S3
```

must not imply:

```text
AE private object storage READY
```

unless credentials are resolved and the bucket is reachable/authorized.

Similarly:

```text
NEX_MO_PROVIDER_MODE=live
```

must not imply planning readiness unless provider admission has passed.

---

# 23. Provisioning Ownership

Application services should generally **not** create infrastructure resources
during normal business request processing.

Recommended ownership:

```text
deployment/bootstrap layer
→ provision/verify dependencies

application runtime
→ consume admitted dependency
```

This avoids:

```text
every API startup creates bucket
business request creates IAM user
worker mutates infrastructure policy
```

---

# 24. OpenBao Separation

OpenBao has two concerns:

```text
A. Secret Retrieval
B. Trust/Policy/Role Provisioning
```

Current product runtime already handles A through:

```text
OpenBaoSecretResolver
production_container_bootstrap
```

Deployment tooling should own B.

Golden Journey runner should not be the only place that knows how B is performed.

---

# 25. Provider Separation

Likewise:

```text
Provider Client
!=
Provider Readiness
```

Golden B v2 requires at least generation.

The deployment profile should declare:

```text
required provider capability = generation
```

and fail closed if it is not admitted.

Golden Journey test may verify the result but should not privately create the provider
configuration after the journey has started.

---

# 26. Five Workstreams

GB2-CA00 is divided into five workstreams.

```text
WS1 Process Topology Promotion
WS2 Generic Runtime Composition
WS3 Domain Activation Registry
WS4 Testing Contract / Smoke Boundary
WS5 Deployment Dependency Readiness
```

---

# 27. WS1 — Process Topology Promotion

## Goal

Promote:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

into current Platform topology.

## Expected Source Areas

```text
services/_shared/nex_runtime/process_manifest.py
services/_shared/nex_runtime/deployment_artifacts.py
services/_shared/nex_runtime/deployment_entrypoints.py
services/_shared/nex_runtime/background_process.py
deployment/*
tests/*
```

## Acceptance

```text
current process manifest contains all three
artifact bindings exist
packaged entrypoints exist
all three are real work processes, not lifecycle-only placeholders
heartbeat/readiness exists
restart semantics tested
current installed topology can run without p8-demo process manifest
```

---

# 28. WS2 — Generic Runtime Composition

## Goal

Extract reusable installed AE runtime composition.

## Must Reuse

```text
existing dispatcher
existing RuntimeJobQueue
existing MultiStepEngine
existing worker runner
existing executor registry
existing approval resume
existing result closer
```

## Must Remove From Generic Layer

```text
Golden A
voucher
demo fixture
demo bundle path
demo Skill root
Chairman demo
```

## Acceptance

```text
generic factory unit tests
Golden A demo adapter still works through generic factory
no semantic behavior change
no new runtime state model
no new queue
no new dispatcher
```

---

# 29. WS3 — Domain Activation Registry

## Goal

Replace direct Demo activator import with general registry.

## Current

```text
semantic_candidate_admission
→ p8_demo_semantic_activation
```

## Target

```text
semantic_candidate_admission
→ DomainIntentActivatorRegistry
    ├─ Golden A finance activator
    ├─ Golden B manufacturing activator [later]
    └─ future activators
```

## Acceptance

```text
unknown capability fail closed where activation is required
duplicate capability registration rejected
Golden A still resolves correctly
capability identity != Skill identity
fixture file not required by generic semantic admission
```

---

# 30. WS4 — Testing Contract

## Goal

Prevent smoke from impersonating Platform runtime.

## Deliverables

```text
docs/development_process.md update
Golden Journey Testing Contract
static audit or test
negative examples
migration of existing relevant smoke acceptance
```

## Acceptance

At least one installed Platform acceptance must prove:

```text
business request submitted
→ no test-side runtime SQL mutation
→ installed worker transitions
→ final result
```

---

# 31. WS5 — Deployment Readiness Contract

## Goal

Move dependency provisioning/readiness knowledge out of Golden Journey runner.

## Initial Dependencies

```text
OpenBao
RustFS/S3-compatible storage
MO generation provider
```

Embedding/reranking may remain optional unless required by the journey.

## Acceptance

```text
deployment bootstrap can prepare dependency independently
readiness can be checked independently
service startup fails closed on missing required dependency
Golden Journey runner consumes readiness, does not create hidden dependency state
```

---

# 32. Proposed Target Runtime Topology

After GB2-CA00:

```text
APIs
────────────────────────────────────
nex-oa-api
nex-mo-api
nex-cx-api
nex-ae-api
nex-ag-api
nex-wc-api
nex-eos-api
nex-wa-api

Web
────────────────────────────────────
nex-ae-web

Core Domain Workers
────────────────────────────────────
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
nex-wa-evidence-consumer

Existing Supporting Workers
────────────────────────────────────
AE artifact renderer
AE retention daemon
AG workers
CX workers
```

This is conceptual; exact inventory must preserve current source-backed workers.

---

# 33. Worker Capability Rule

Every worker/daemon in current manifest should be classified as:

```text
job_claiming
event_delivering
outbox_publishing
scheduled_maintenance
lifecycle_only
```

A process marked:

```text
lifecycle_only
```

must not be used as evidence that domain work is active.

This directly addresses the historical:

```text
domain_claiming_enabled=true
but no actual domain handler
```

problem.

---

# 34. Runtime Readiness Rule

Worker readiness should prove not only:

```text
process alive
DB reachable
```

but when required:

```text
handler composition available
executor kinds available
backend profile available
service trust available
dependency readiness available
```

Fail closed if the worker is configured to claim work without its handler.

---

# 35. Proposed Source Layout

Illustrative only:

```text
services/nex-ae-api/nex_ae_api/
  runtime_composition.py
  domain_intent_activators.py
  domain_intent_registry.py

services/nex-wc/nex_wc/
  worker_runtime.py

services/nex-eos/nex_eos/
  outbox_worker_runtime.py

services/_shared/nex_runtime/
  dependency_readiness.py
  process_manifest.py
  deployment_entrypoints.py
```

Exact names are not normative.

---

# 36. Smoke-to-Product Promotion Rule

When a demo/smoke discovers a missing runtime composition:

```text
do not permanently fix only the runner
```

Required sequence:

```text
1. identify missing Platform component
2. implement/compose under owning service/runtime
3. expose installed entrypoint
4. make smoke call installed path
5. delete/reduce duplicate runner-side composition
```

---

# 37. Legacy Demo Code Policy

Do not delete P8-DEMO evidence code merely because a generic replacement exists.

Historical evidence must remain reproducible where practical.

Preferred migration:

```text
p8_demo_* wrapper
→ canonical Platform component
```

rather than:

```text
delete old module
→ break historical evidence
```

---

# 38. No Architecture Expansion

GB2-CA00 SHALL NOT introduce:

```text
new business workflow semantics
new approval domain
new AgentExecution trigger
new NSL language syntax
new scheduler
new event broker
new WorkItem model
new WorkAsset model
Golden C
autonomous PA
```

The goal is promotion/integration, not feature expansion.

---

# 39. Golden B v2 Entry Gate

Golden B v2 implementation SHALL NOT begin until:

```text
WS1 PASS
WS2 PASS
WS3 PASS
WS4 PASS
WS5 PASS
```

At minimum, Core Golden B runtime must be reachable from:

```text
current Platform topology
```

without requiring:

```text
p8-demo-only installed process manifest
manual runtime composition in smoke
runtime transition fixture
```

---

# 40. Preliminary Audit Work Packages (Non-Canonical)

The source-audit stage originally used the following preliminary work packages
to test sequencing. They are retained as design rationale, not as executable
Slice identifiers:

```text
AUDIT-WP01
Current process topology source audit + target inventory freeze

AUDIT-WP02
Promote AE Agent Runtime worker

AUDIT-WP03
Promote WC event-delivery worker

AUDIT-WP04
Promote EOS outbox publisher

AUDIT-WP05
Extract generic AE installed runtime composition

AUDIT-WP06
Rebind P8-DEMO runtime through generic factory

AUDIT-WP07
Introduce DomainIntentActivatorRegistry

AUDIT-WP08
Migrate Golden A activator out of demo-only generic dependency

AUDIT-WP09
Add Golden Journey testing contract + static audit

AUDIT-WP10
Introduce deployment dependency readiness contract

AUDIT-WP11
Promote OpenBao/RustFS/provider provisioning/readiness boundary

AUDIT-WP12
Installed current-Platform continuity acceptance

AUDIT-WP13
Repository Full Gate / final closure
```

The canonical executable sequence is exclusively the `GB2-CA00-S01` through
`GB2-CA00-S20` sequence in
`261028_GB2_CA00_Platform_Runtime_Internalization_Implementation_Slice_Plan_v1.1.md`.
The mapping is:

```text
WP01       -> S01
WP02-WP04 -> S02, S05-S08
WP05       -> S03
WP06       -> S04, S17
WP07-WP08 -> S09-S11
WP09       -> S12
WP10-WP11 -> S13-S16
WP12       -> S18-S19
WP13       -> S20
```

---

# 41. Audit WP01 — Process Inventory Freeze

Produce exact matrices:

```text
Process
Owner
Artifact
Entrypoint
Execution Model
Database
Dependency
Heartbeat
Work Capability
Restart Contract
```

Compare:

```text
historical platform
P8-DEMO
current P9
target current
```

No coding before ambiguity is removed.

---

# 42. Audit WP02-WP04 — Worker Promotion

For each worker:

```text
process manifest
artifact binding
packaged command
database env
service trust
heartbeat
readiness
restart
work loop
```

must be source-backed.

No worker is considered promoted if only:

```text
--check
```

works.

It must execute real bounded work in protected acceptance.

---

# 43. Audit WP05 — Generic AE Composition

Extract from:

```text
p8_demo_runtime_composition.py
```

while preserving:

```text
dispatcher semantics
worker semantics
RuntimeJob semantics
MultiStepEngine semantics
NSL Approval semantics
Controlled WRITE semantics
result finalization semantics
```

No state-machine rewrite.

---

# 44. Audit WP06 — Demo Compatibility

P8-DEMO must continue to work using the generic factory.

This is a regression requirement.

```text
old Demo behavior
→ same observable semantics
→ less demo-owned orchestration
```

---

# 45. Audit WP07-WP08 — Activator Registry

Move generic semantic admission away from direct:

```text
p8_demo_semantic_activation
```

dependency.

Golden A becomes a registered domain profile.

The registry should allow Golden B later without editing core semantic admission logic.

---

# 46. Audit WP09 — Testing Contract

Update development policy with:

```text
Business Fixture allowed
Runtime Transition Fixture forbidden
Installed Golden Journey rules
Evidence classification
```

Add automated checks where practical.

---

# 47. Audit WP10-WP11 — Dependency Readiness

Create canonical dependency readiness contracts and bootstrap paths.

At least:

```text
OpenBao
AE object storage
generation provider
```

should be independently provisionable/checkable.

P8-DEMO scripts may become wrappers over canonical bootstrap.

---

# 48. Audit WP12 — Installed Current Platform Acceptance

This is the key acceptance.

Use current Platform topology, not P8 Demo process manifest.

Minimum journey may reuse Golden A because it already exercises:

```text
planning
runtime worker
approval
controlled WRITE
EOS
result finalization
```

The objective is not Golden A business validation.

The objective is:

```text
current Platform process continuity
```

Acceptance must prove:

```text
request
→ semantic admission
→ schedule_next
→ current AE worker
→ approval
→ current WC worker
→ resume
→ controlled WRITE
→ current EOS publisher
→ result
```

without test-side runtime transition mutation.

---

# 49. Audit WP13 — Full Closure

Run:

```text
affected unit tests
worker tests
deployment manifest tests
P8-DEMO compatibility
current Platform installed acceptance
Repository Full Gate
zero residue
git diff --check
```

Coverage floor remains:

```text
Statement >= 96%
Branch    >= 94%
```

---

# 50. Protected Acceptance Rules

Protected acceptance may seed:

```text
tenant
user
project
account/business master
service principal
business source fixture
```

After request submission:

```text
no runtime INSERT/UPDATE by runner
no direct schedule_next by runner
no direct WorkResult submit through repository
no direct approval persistence
```

The runner may still:

```text
poll
assert
restart
query
cleanup after completion
```

---

# 51. Acceptance Matrix

| Area | Required result |
|---|---|
| AE worker | current Platform first-class work-claiming process |
| WC worker | current Platform first-class delivery process |
| EOS worker | current Platform first-class outbox publisher |
| AE composition | generic installed factory |
| P8 Demo | wrapper/profile over generic factory |
| semantic activation | registry-based |
| Golden A | registered capability profile |
| smoke | no post-request transition fixture |
| RustFS | provision/readiness contract |
| OpenBao | provisioning vs resolution separation |
| provider | live readiness contract |
| Full Gate | PASS |
| coverage | 96/94 or higher |
| residue | zero owned test residue |

---

# 52. P0 / P1 Priorities

## P0

```text
P0-01 current Platform missing AE runtime worker
P0-02 current Platform missing WC delivery worker
P0-03 current Platform missing EOS outbox publisher
P0-04 generic runtime composition absent
P0-05 product semantic admission directly depends on Demo activator
P0-06 Golden Journey can be falsely accepted through test-side transition
```

## P1

```text
P1-01 dependency readiness/provisioning remains demo-oriented
P1-02 process capability vocabulary should distinguish real work vs lifecycle
P1-03 capability registration should be independent of fixture paths
P1-04 historical demo wrappers should converge on canonical components
```

---

# 53. Explicitly Resolved Historical Issues

The following are already source-backed as corrected and are not primary
GB2-CA00 implementation targets.

```text
Capability:
  FINANCE.CREATE_VOUCHER_DRAFT

Skill:
  FINANCE.VOUCHER_DRAFT_CREATE

→ correctly distinct
```

Also:

```text
COMPILED
→ semantic admission scheduler.schedule_next()
```

exists.

NSL Approval resume now exists in MultiStepEngine:

```text
LOCAL_SKILL
+
NSL_APPROVAL wait
+
RESUME_EXECUTION
```

OA DB constraints now admit:

```text
nex-wc
nex-eos
nex-wa
```

through later migrations.

The historical `claimed_count` vs `execution_count` composition mismatch was
corrected in the Demo composition.

These should remain regression-protected.

---

# 54. Remaining Hard-Coded / Demo-Coupled Areas to Audit

At implementation start, audit at least:

```text
p8_demo_runtime_composition.py
p8_demo_controlled_skill.py
p8_demo_semantic_activation.py
demo_runtime.py
demo_processes.py
demo_domain_activation.py
demo_domain_installation.py
run_p8_demo_s10_installed_domain_acceptance.py
run_p8_demo_s11_chairman_golden_journey.py
run_p8_demo_s10b_installed_runtime.py
```

Classify every dependency:

```text
Platform canonical
Demo profile
Test-only
Historical evidence
Must promote
May remain
Must remove from runtime path
```

---

# 55. Platformization Classification

Use these labels:

```text
P — PLATFORM CANONICAL
D — DEMO PROFILE
T — TEST ONLY
H — HISTORICAL EVIDENCE
X — INVALID RUNTIME DEPENDENCY
```

Example:

```text
SqlAlchemyMultiStepEngine            P
run_bounded_agent_runtime_worker     P
P8DemoControlledSkillRuntime         D
p8_golden_a_fixture.v1.json          D/T
direct runtime SQL transition        X
```

This inventory should be committed as part of the first Slice.

---

# 56. Documentation Deliverables

GB2-CA00 should produce:

```text
1. Source Audit / Pre-Architecture Decision [this document]
2. Platform Runtime Process Inventory
3. Smoke-to-Product Testing Contract
4. Deployment Dependency Readiness Contract
5. Implementation Slice Plan
6. Final As-Built / Golden B v2 Entry Handoff
```

---

# 57. Recommended New Development Rule

Add to `docs/development_process.md`:

```text
Platform Integration Rule

A new capability is not complete when its only executable composition exists
inside tests, smoke, demo runner, or deployment acceptance code.

If a capability requires a long-lived process, background consumer, scheduler,
dispatcher, publisher, or continuation handler, the owning Platform runtime
must provide a canonical installed composition and entrypoint.
```

---

# 58. Recommended Golden Scenario Rule

All future Golden A/B/C/D acceptance should include:

```text
platform_integrated = true
runtime_transition_fixture = false
installed_process_continuity = true
```

This will prevent future regressions into smoke-owned orchestration.

---

# 59. Golden B v2 Impact

Once GB2-CA00 closes, Golden B v2 becomes simpler.

Before:

```text
Golden B v2
→ must solve manufacturing
→ must solve runtime installation
→ must solve domain registry
→ must solve worker promotion
→ must solve dependency bootstrap
```

After:

```text
Golden B v2
→ manufacturing business source
→ PA capability
→ Artifact/report
→ Full Journey acceptance
```

This separation is strategically important.

---

# 60. Stop Conditions

Return to architecture review if implementation attempts to:

```text
create a second runtime worker framework
create a second dispatcher
create a second approval/resume engine
introduce a broker solely to connect existing workers
move business fixture into Platform runtime
allow test code to remain the only transition owner
make OpenBao/RustFS provisioning a business-request side effect
change Frozen AgentExecution triggers
```

---

# 61. Final Decision

The five identified problems are real and should be corrected before Golden B v2
business implementation proceeds.

Source review shows:

```text
P8-DEMO proved the missing installed composition can work.

P9 promoted parts of the deployment baseline.

But full domain-runtime promotion is incomplete.
```

Therefore the recommended sequence is:

```text
P9 Closed
        ↓
GB2-CA00
Platform Runtime Internalization
        ↓
Smoke-to-Product Promotion
        ↓
Installed Current Platform Acceptance
        ↓
GB2-CA00 Final As-Built
        ↓
Golden B v2 Design Freeze
        ↓
Golden B v2 Implementation
```

The guiding principle is:

> **Smoke should prove that the Platform works; Smoke must not be the thing that
> makes the Platform work.**
