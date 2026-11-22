# NeX MyBee W70-CA01: NSL Tool, Product Capability Registry, and Skill-Pack Entry Reconciliation v1.0

## 1. Status And Authority

- Decision date: `2026-11-15`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `a5c5fa7c4af1cf69c75d17c8505fdd734c16d488`
- Runtime code changes by this document: none
- Database migration authorized by this document: none
- Remote model-provider dependency for this document: none

This controlled amendment reconciles the completed W40, W50, and W60
accounting foundations with the planned W70 NSL Tool, product capability
registry, and D04/D12 Skill-Pack entry boundary.

It does not rewrite the frozen PAD, SRS, or v1.2 Slice Plan. It takes
precedence only where the original W70 paths, operation identities, dependency
statuses, registry assumptions, or Gate grouping no longer match the current
repository.

## 2. W70 Entry Decision

W70 may begin after this amendment because its business authorities now exist:

1. EOS exposes the current VoucherCandidate, Posting, FX, allocation, Budget,
   Project P&L, and Project operations through versioned OpenAPI contracts.
2. AE already owns an immutable product capability registry, exact-version
   Skill artifact admission, NSL v0.2.1 runtime integration, approval resume,
   controlled WRITE, verification, and reconciliation foundations.
3. NSL v0.2.1 is admitted by an immutable wheel lock. W70 does not require an
   NSL compiler or runtime change.
4. W60 closed with actual EOS and OA PostgreSQL acceptance while preserving
   immutable GL lineage, Project authorization, and aggregate payroll privacy.
5. The original S8-01 plan is still directionally correct, but its proposed
   schema filenames, legacy Golden A identifiers, and one-entry registry model
   are older than the current source.

W70 is therefore authorized to productize canonical Tool contracts and signed
D04/D12 Skill Packs. It is not authorized to create a parallel accounting API,
a second capability registry, a second NSL runtime, or a duplicate business
ledger.

## 3. Source-Backed Current State

| Boundary | Confirmed source state | W70 consequence |
| --- | --- | --- |
| EOS wire authority | `contracts/openapi/nex-eos.openapi.yaml` and its referenced JSON Schemas describe the current service contract | Existing path, request, result, and schema identities are the starting authority; proposed duplicate `eos_*_v2` files are not created merely because they appeared in the old plan |
| VoucherCandidate | `FINANCE.VOUCHER_CANDIDATE.CREATE_V2`, `GET_V2`, `REVISE`, `VALIDATE`, and review operations already exist | S8-01 binds and validates these contracts instead of introducing another VoucherCandidate family |
| Posting | `FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION` and `FINANCE.VOUCHER.APPROVE_AND_POST` already enforce proof, fresh OA authority, and atomic Posting | NSL Tools may consume these boundaries but must not bypass or weaken them |
| Allocation | SourcePool, approved AllocationPlan, deterministic Allocation run, and verification operations exist | Tool activation must preserve released-plan, conservation, idempotency, and verification requirements |
| Project P&L | `FINANCE.PROJECT_PNL.GET` and `project_pnl_projection.v1.schema.json` exist | W70 exposes the existing privacy-protected read model; it does not create another P&L query schema or projection |
| Legacy Golden A operation | Runtime code and capability registration use `FINANCE.CREATE_VOUCHER_DRAFT`; OpenAPI POST currently uses `createEosVoucherDraft` | These are compatibility identities, not the naming pattern for new Tools |
| AE product registry | `ae.product_capability_registry.v1` supports up to 64 immutable, canonically ordered registrations but the deployed file contains one Golden A registration | W70 versions and extends the existing registry; it does not add a parallel registry implementation |
| Product NSL bundle | The current lock admits NSL v0.2.1 and one `FINANCE.VOUCHER_DRAFT_CREATE` Skill | The old artifact remains replayable; new D04/D12 artifacts receive independent exact versions and digests |
| Historical Skill source | The existing bundle lock records `examples/golden_a_voucher_draft`, which is not present in the reviewed NeX tree | New MyBee Skill source and manifest ownership must be repository-visible under `domains/mybee/skills/`; the historical lock remains evidence, not a source template |
| MyBee domain | `domains/mybee` owns policy, catalogs, templates, and canonical service consumers; no `skills/` directory exists yet | W70 may add the first admitted D04/D12 Skill-Pack source without moving service or runtime ownership into MyBee |
| W60 handoff | W60 is `CLOSED` and defers NVT rollup, richer HR/payroll, procurement/inventory, and BOM implementation | W70 cannot silently absorb those deferred business authorities into Tool logic |
| W70 planning | The matrix labels only S8-01 as the W70 original packet, while the roadmap also places three M1 checkpoint packets in W70 | S8-01 foundation acceptance and W70 M1 public E2E acceptance are separate Gates |

## 4. Normative Decisions

### W70-CA01-ADR-01: EOS OpenAPI And Referenced Schemas Are Canonical

The current EOS OpenAPI document and the JSON Schemas it references are the
canonical wire contracts for W70. Python request models, NSL Tool examples,
Skill manifests, and MyBee clients are consumers of those contracts; none may
silently redefine them.

W70 implementation must:

- reuse current schema names such as `voucher_candidate_create.v2`,
  `accounting_posting_admission.v1`, `journal_post_command.v1`,
  `cost_allocation_run.v1`, and `project_pnl_projection.v1`;
- add a new schema only when the OpenAPI operation genuinely has no adequate
  canonical request or result schema;
- use an additive version when a wire-shape change is required;
- keep tenant, company, Project, proof, idempotency, payload-hash, evidence,
  and trace fields aligned with EOS validation; and
- reject Tool contracts whose example payload compiles but does not validate
  against the referenced canonical schema.

The proposed S8-01 filenames in the v1.2 plan are target suggestions, not
authority. Creating a second schema with the same business meaning is
prohibited.

### W70-CA01-ADR-02: Freeze Canonical Operation Naming

New operation identities follow this logical form:

```text
<DOMAIN>.<BUSINESS_OBJECT>.<ACTION>
```

Rules:

1. Identifiers use uppercase ASCII letters, digits, and underscores inside a
   segment. Dots separate semantic segments.
2. `DOMAIN` is the owning business domain, for example `FINANCE` or `PROJECT`.
3. `BUSINESS_OBJECT` names the governed object before the verb, for example
   `VOUCHER_CANDIDATE`, `COST_ALLOCATION`, or `PROJECT_PNL`.
4. `ACTION` is an explicit verb or stable verb phrase such as `GET`, `CREATE`,
   `CREATE_V2`, `VALIDATE`, `RELEASE`, `RUN`, or `VERIFY`.
5. A new identifier must not place the verb before the business object.
6. API operation IDs, capability IDs, Tool IDs, audit records, and operator
   evidence emit the canonical identity. An accepted compatibility alias is
   recorded separately as `invoked_alias` and never replaces the canonical
   value in new evidence.
7. Event type naming and immutable Skill artifact selectors are distinct
   namespaces. They are not renamed merely to resemble an operation ID.

Published EOS identities remain authoritative for their current wire
contracts. Historical outliers are grandfathered until a contract-major
retirement rather than being destructively renamed during W70. New W70
identities must not introduce another outlier.

### W70-CA01-ADR-03: Preserve Golden A Through Explicit Compatibility Aliases

The legacy identities below remain supported during W70:

| Legacy identity | Namespace | Canonical W70 identity | W70 state |
| --- | --- | --- | --- |
| `FINANCE.CREATE_VOUCHER_DRAFT` | EOS/AE operation and capability | `FINANCE.VOUCHER_DRAFT.CREATE` | `ACTIVE_COMPATIBILITY` |
| `createEosVoucherDraft` | OpenAPI operationId | `FINANCE.VOUCHER_DRAFT.CREATE` | `ACTIVE_COMPATIBILITY` |
| `FINANCE.VOUCHER_DRAFT_CREATE` | Historical Skill selector | no in-place rename; exact artifact identity retained | `REPLAY_ONLY_COMPATIBILITY` for the old artifact |

Compatibility policy:

- aliases are resolved at the Tool/capability admission boundary before
  execution;
- new plans, manifests, and evidence emit only the canonical operation ID;
- existing plans, receipts, idempotency identities, and signed artifacts keep
  their historical identifiers and hashes;
- alias resolution must be one-to-one, cycle-free, immutable within a registry
  version, and covered by collision tests;
- registry v1 remains immutable evidence; W70 creates a higher registry
  version rather than editing a historical hash in place; and
- retirement follows `ACTIVE_COMPATIBILITY -> DEPRECATED -> DISABLED`.
  W70 does not advance beyond `ACTIVE_COMPATIBILITY`.

An alias can be disabled only after full S8-02/S8-03 acceptance, active-plan
inventory proves no unresolved reference, rollback evidence is retained, and
a separate Controlled Amendment authorizes retirement.

### W70-CA01-ADR-04: Separate Invocation Semantics, Approval, And Activation

Every registered Tool records three independent decisions:

| Axis | Allowed values | Meaning |
| --- | --- | --- |
| Invocation semantics | `READ`, `GOVERNED_WRITE` | Whether the operation is side-effect-free or may mutate an authoritative service |
| Approval requirement | `NONE`, `NSL_WRITE`, `BUSINESS_FORMAL`, `ACCOUNTING_POSTING`, or an ordered combination | Which exact proof must be present before dispatch |
| Activation state | `CANDIDATE`, `SHADOW`, `ACTIVE`, `ACTIVE_COMPATIBILITY`, `DEFERRED`, `DISABLED` | Whether planning and runtime dispatch may select the Tool |

`GOVERNED_WRITE` does not automatically mean that a new human approval is
required for every invocation. It always requires current service trust,
fresh OA authorization where the OpenAPI declares a business scope,
idempotency, canonical payload hashing, durable evidence, and an explicit
verification/reconciliation policy. The manifest separately names any human
proof requirement.

The initial W70 admission inventory is:

| Canonical operation | Semantics | Required authority/proof | Entry state |
| --- | --- | --- | --- |
| `FINANCE.VOUCHER_DRAFT.CREATE` | `GOVERNED_WRITE` | `finance:voucher-draft:create`, NSL WRITE approval/evidence | `ACTIVE_COMPATIBILITY` through the existing Golden A path; canonical alias activation requires S8-01 Gate |
| `FINANCE.VOUCHER_CANDIDATE.CREATE_V2` | `GOVERNED_WRITE` | `finance:voucher-candidate:create`, canonical source proof, idempotency | `CANDIDATE` |
| `FINANCE.VOUCHER_CANDIDATE.GET_V2` | `READ` | current service and tenant scope; Project/OA read policy must be explicit before product activation | `DEFERRED` until S8-01 scope reconciliation |
| `FINANCE.VOUCHER_CANDIDATE.VALIDATE` | `READ` | exact Candidate revision and authoritative accounting/FX/period inputs | `CANDIDATE` |
| `FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION` | `READ` | `finance:journal:approve`, exact `ACCOUNTING_POSTING` proof, human SoD | `CANDIDATE` |
| `FINANCE.VOUCHER.APPROVE_AND_POST` | `GOVERNED_WRITE` | admitted Posting receipt, `finance:journal:approve`, idempotency, verification/reconciliation | `CANDIDATE` |
| `FINANCE.COST_ALLOCATION_PLAN.RELEASE` | `GOVERNED_WRITE` | `finance:cost-allocation-plan:approve`, BUSINESS_FORMAL proof | `CANDIDATE` |
| `FINANCE.COST_ALLOCATION.RUN` | `GOVERNED_WRITE` | `finance:allocation:execute`, released immutable plan, idempotency and conservation | `CANDIDATE` |
| `FINANCE.COST_ALLOCATION.VERIFY` | `READ` | `finance:allocation:verify`, exact batch identity | `CANDIDATE` |
| `FINANCE.FX_RATE.IMPORT` | `GOVERNED_WRITE` | `finance:fx:publish`, admitted source-policy lineage | `CANDIDATE` |
| `FINANCE.FX_RATE.RESOLVE` and `FINANCE.FX_RATE.HISTORY` | `READ` | `finance:fx:read`, tenant/company policy where applicable | `CANDIDATE` |
| `FINANCE.PROJECT_PNL.GET` | `READ` | `project:pnl:read`, Project entitlement and privacy guard | `CANDIDATE` for NSL Tool activation; EOS API already active |

No `CANDIDATE` operation becomes selectable merely because its JSON Schema
validates. Activation requires the applicable S8-01 registry, artifact, trust,
negative, authorization, and evidence Gates.

### W70-CA01-ADR-05: Extend The Existing AE Registry And Bundle Model

W70 reuses:

- `ProductCapabilityRegistry` and `ae.product_capability_registry.v1`;
- `SkillArtifactGateway` and persisted verified Skill artifact evidence;
- the NSL v0.2.1 wheel admission lock;
- product runtime capability merging and exact-version selection; and
- existing approval, idempotency, WRITE evidence, post-write verification,
  and reconciliation ports.

The implementation must create a new immutable registry release containing
canonically sorted registrations. Each registration binds exactly one
capability version to one exact Skill version, semantic hash, runtime contract,
trust policy, backend profile, and bundle manifest.

One registry release may reference multiple immutable bundle manifests. A
single historical one-Skill bundle is not expanded by mutating its digest.
New D04/D12 bundles receive new bundle IDs and locks. The registry must fail
closed on duplicate capability IDs, alias collisions, missing manifests,
Skill/bundle mismatches, digest mismatches, unsigned packages, inactive trust,
or unsupported runtime contracts.

W70 does not create `nex_tool_bindings.py` as a second runtime registry. A
MyBee integration module may expose typed, transport-neutral Tool descriptors
for domain consumers, but executable selection remains owned by the AE product
capability registry and Agent Runtime.

### W70-CA01-ADR-06: Define D04/D12 Skill-Pack And Evidence Contracts

Repository-visible source ownership is:

```text
domains/mybee/skills/d04_accounting/
domains/mybee/skills/d12_project/
```

Each Skill-Pack manifest must contain at least:

- manifest schema version, pack ID, domain code, exact pack version, and
  activation state;
- canonical operation ID and any admitted compatibility aliases;
- capability ID/version and exact Skill ID/version;
- input and output contract references resolved to canonical NeX schemas;
- invocation semantics and activation state;
- required service scope and exact OA business action, or the explicit
  `NONE_SERVICE_TRUST_ONLY` decision with justification;
- approval profile and proof/evidence type;
- idempotency, replay, payload-hash, verification, reconciliation, timeout,
  and UNKNOWN-outcome policies;
- wheel lock, runtime contract, backend profile, trust-policy ID, publisher,
  signing-key identity, package hash, Skill semantic hash, and bundle ID; and
- source files and exact byte digests in deterministic lexical order.

Digest rules:

1. JSON is normalized with the shared `nex_runtime.semantic_hashes` canonical
   JSON and SHA-256 helpers. A second MyBee-local hash implementation is
   prohibited.
2. Source-file digests use exact bytes. Manifest semantic hashes use canonical
   JSON and exclude only their own final hash field.
3. Registry, bundle, package, Skill, contract, payload, approval, and evidence
   hashes remain distinct typed identities and must not be substituted for one
   another.
4. Any source, contract reference, OA action, approval profile, runtime
   policy, or artifact selector change requires a new immutable manifest or
   pack version.

The OA action is derived from the canonical OpenAPI `x-nex-business-scope` and
current OA policy. A Skill manifest cannot invent a broader action, infer an
action from a role name, or omit fresh authorization because a service token
is valid.

Evidence requirements by semantics:

| Tool class | Minimum durable evidence |
| --- | --- |
| `READ` | tenant/subject/Project scope, canonical operation, contract version, query hash, OA decision when required, source/result hash, trace, observed time |
| `GOVERNED_WRITE` | all READ identity evidence plus idempotency key, canonical payload hash, approval proof where required, write-requested receipt, commit outcome, verification, reconciliation or typed UNKNOWN, trace |
| Approval-required | exact approval domain, case/request ID, approved payload hash, approver authority snapshot, terminal proof reference, freshness decision |

### W70-CA01-ADR-07: Prohibit NSL Core Changes And New Persistence

S8-01 is a contract, registry, manifest, and artifact-admission Slice. It must
not modify:

- the NSL compiler, parser, operation kinds, runtime coordinator, or public API;
- the admitted NSL v0.2.1 wheel or its immutable lock;
- AE, EOS, OA, WC, or MyBee database schemas;
- existing Journal, allocation, P&L, approval, or authorization persistence; or
- service-private tables through cross-service access.

No new database migration is authorized. A discovered need for a new NSL
operation kind, runtime primitive, evidence port, or persistence table stops
S8-01 and requires a separate source-backed decision.

### W70-CA01-ADR-08: Separate S8-01 Foundation From W70 M1 E2E

#### Gate A: S8-01 Foundation Gate

S8-01 closes only when:

- canonical OpenAPI/schema references and examples validate;
- positive and negative Tool contracts compile against the admitted NSL
  v0.2.1 public API without modifying NSL core;
- operation naming, aliases, activation state, OA actions, and approval
  profiles pass deterministic validation;
- D04/D12 manifests, source digests, bundle locks, and registry hashes match;
- duplicate, mismatched, unsigned, untrusted, stale, unsupported, and
  cross-tenant cases fail closed; and
- existing Golden A registry and controlled-WRITE regression remains green.

Gate A does not require a remote embedding, reranking, or generation provider.
It does not claim that the public IA/PA journey or M1 is complete.

#### Gate B: W70 M1 Public E2E Gate

The W70 roadmap checkpoint consists of:

1. `CP-M1-S8-02`: AE/NSL Journal WRITE CREATE, immediate EOS read-after-write
   verification, and typed UNKNOWN lookup;
2. `CP-M1-MB8-01`: signed minimal D04/D12 Skill, FL mapping, and PA/NSL
   invocation; and
3. `CP-M1-E2E-FX-01`: public IA/PA -> WC/OA -> EOS USD Journal -> allocation
   and Project P&L -> WA result journey.

Gate B requires actual service composition, signed trust, protected PostgreSQL
authorities, and live generation where natural-language planning is exercised.
It prohibits direct runtime-transition SQL, direct EOS/WC private-state calls,
hard-coded smoke results, or replacement of unavailable product paths with
test-only fixtures.

Passing Gate B is the M1 checkpoint declaration. It does not close the full
original S8-02 or S8-03 packets whose later-wave dependencies remain binding.

### W70-CA01-ADR-09: Preserve W60 Accounting, Authorization, And Privacy

Every W70 Tool and Skill Pack must preserve:

- immutable, insert-only PostedJournal header/line truth;
- exact VoucherCandidate, approval, Posting, Journal, SourcePool, allocation,
  payroll/material, and P&L lineage;
- one management-recognition path and `E = D + A + U` conservation;
- fresh OA authorization, Project-Code entitlement, tenant/company/Project
  isolation, and human SoD;
- append-only allocation and P&L projection correction rather than mutation;
- aggregate payroll privacy and difference-attack protection;
- explicit confirmed, provisional, committed, unassigned, unallocated,
  pending, and stale classifications; and
- W60 deferrals for NVT rollup, full HR/payroll, procurement/inventory, BOM,
  and Project-close blocking.

An LLM, Skill, Tool mapper, or PA may select and explain a canonical operation.
It cannot fabricate accounting authority, approval, FX, Project entitlement,
allocation evidence, payroll detail, or a successful verification outcome.

## 5. Corrected W70 Implementation Boundary

The recommended implementation sequence is:

| Order | Slice | Scope |
| --- | --- | --- |
| 1 | `W70-CA01` | This source-backed entry and precedence decision |
| 2 | `W70-S8-01A` | Canonical Tool inventory, operation naming, legacy alias map, and activation profile |
| 3 | `W70-S8-01B` | Canonical JSON Schema/OpenAPI reference validation and negative examples |
| 4 | `W70-S8-01C` | D04/D12 Skill-Pack manifests, source layout, exact digests, and trust metadata |
| 5 | `W70-S8-01D` | Versioned AE product capability registry and immutable multi-bundle locks |
| 6 | `W70-S8-01E` | S8-01 compile, admission, alias, trust, and regression Gate |
| 7 | `CP-M1-S8-02` | Checkpoint-only controlled Journal execution, verification, and UNKNOWN handling |
| 8 | `CP-M1-MB8-01` | Checkpoint-only signed D04/D12 Skill and PA orchestration |
| 9 | `CP-M1-E2E-FX-01` | Protected public M1 E2E and W70 closure |

The exact split may be compressed only if each commit remains independently
reviewable and the two Gate classes remain separate. S8-01E must complete
before any M1 checkpoint advertises a newly registered Tool as active.

## 6. Required Verification

### 6.1 S8-01 Focused Verification

- OpenAPI validation and JSON Schema positive/negative validation;
- canonical operation naming and alias collision tests;
- registry canonical ordering, versioning, and hash tests;
- Skill-Pack source digest, semantic hash, bundle lock, and exact-version tests;
- NSL v0.2.1 compile/admission tests with zero compiler/runtime changes;
- OA action and approval-profile completeness tests;
- READ/WRITE activation and fail-closed dispatch tests;
- Golden A compatibility and historical replay tests; and
- boundary-import tests preventing MyBee from importing service-private code.

### 6.2 W70 Protected Verification

- actual AE, OA, WC, EOS, WA, and applicable MyBee PostgreSQL-backed paths;
- signed service-token and current OA authorization checks;
- exact approval/payload/Skill/registry/bundle/evidence hash lineage;
- restart, replay, duplicate ACK, timeout, UNKNOWN, and rollback behavior;
- public API/browser journey without private-state shortcuts;
- live generation only for the natural-language planning segment; and
- zero-residue cleanup plus Repository Full Gate at the W70 closure boundary.

## 7. Explicit Non-Goals

W70-CA01 and S8-01 do not:

- implement full S8-02, S8-03, or later M2/M3/M4 packets;
- change NSL v0.2.1 source, wheel, compiler, runtime, or public API;
- add a database migration or new authoritative table;
- replace EOS OpenAPI/schema authority with Skill-local schemas;
- retire Golden A aliases;
- activate every EOS operation as an Agent Tool;
- add NVT rollup, Project close, HR/payroll, procurement, inventory, BOM, or
  richer FX settlement behavior;
- expose individual payroll or salary detail; or
- use a remote model-provider response as accounting, approval, or
  authorization evidence.

## 8. Stop Conditions

Implementation stops for a new decision if any of the following occurs:

1. a Tool requires a schema that conflicts with the current EOS wire contract;
2. canonical and legacy identities cannot be mapped one-to-one;
3. a required OA action or approval domain is absent or ambiguous;
4. an existing operation marked side-effect-free performs an authoritative
   mutation;
5. a new NSL operation kind, runtime API, database table, or migration appears
   necessary;
6. a Skill artifact cannot be rebuilt from repository-visible source and
   immutable locks;
7. activation would bypass W40/W50/W60 Posting, allocation, P&L,
   authorization, or privacy invariants; or
8. a smoke path can pass only through hard-coded fixtures or direct private
   service state.

## 9. Closure Statement

```text
W60 implementation closure       = CLOSED
W70-CA01 design reconciliation   = CLOSED
S8-01 implementation             = NOT STARTED BY THIS DOCUMENT
W70 M1 public E2E                = NOT STARTED BY THIS DOCUMENT
NSL compiler/runtime change      = PROHIBITED
new database migration           = PROHIBITED
remote provider for S8-01        = NOT REQUIRED
```

W70 implementation may begin with `W70-S8-01A` only after this document is
reviewed and admitted into the MyBee Phase-1 reading order.
