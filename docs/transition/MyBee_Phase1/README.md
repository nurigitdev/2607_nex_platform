# NeX MyBee Phase-1 Design Baseline

This directory is the canonical transition-document set for the NeX-based
MyBee office-work AX Service Phase-1 program.

## Reading Order

1. `NeX_MyBee_D04_D12_Accounting_Transaction_Contract_Closure_v1.0_RC1.md`
2. `NeX_MyBee_D04_D12_EOS_Source_Audit_and_Gap_Analysis_v1.0.md`
3. `NeX_MyBee_D04_D12_Pre_Architecture_Decision_v1.0.md`
4. `NeX_MyBee_D04_D12_EOS_SRS_v1.0.md`
5. `NeX_MyBee_Phase1_InRepo_Deferred_EOS_ADR_v1.0.md`
6. `NeX_MyBee_Phase1_InRepo_Ownership_Override_v1.0.json`
7. `NeX_MyBee_Phase1_CA01_Pre_Implementation_Document_Consistency_Closure_v1.0.md`
8. `NeX_MyBee_Implementation_Slice_Plan_v1.2.md`
9. `NeX_MyBee_Implementation_Slice_Plan_Execution_Matrix_v1.2.json`
10. `NeX_MyBee_W30_CA01_W20_to_W30_Entry_Reconciliation_v1.0.md`
11. `NeX_MyBee_W30_CA01_Entry_Decision_v1.0.json`
12. `NeX_MyBee_W30_CA02_Project_Application_Code_Lifecycle_and_PA_Contract_Closure_v1.0.md`
13. `NeX_MyBee_W40_CA01_Project_Membership_and_OA_Project_Code_Entitlement_Contract_Closure_v1.0.md`
14. `NeX_MyBee_W40_CA02_Accounting_Product_Runtime_Integration_Checkpoint_v1.0.md`
15. `NeX_MyBee_W40_S4_00A_Pre_Posting_VoucherCandidate_Revision_and_Journal_Boundary_Hardening_v1.0.md`
16. `NeX_MyBee_W50_CA01_W40_to_W50_Allocation_Entry_Reconciliation_v1.0.md`
17. `NeX_MyBee_W60_CA01_Project_PnL_Projection_and_Management_Allocation_Entry_Reconciliation_v1.0.md`
18. `NeX_MyBee_W70_CA01_NSL_Tool_Product_Capability_Registry_and_Skill_Pack_Entry_Reconciliation_v1.0.md`
19. `NeX_MyBee_W70_CA02_Installed_PA_Delegation_and_Multi_Skill_Runtime_Composition_Closure_v1.0.md`
20. `NeX_MyBee_CP_M1_GA_RET_02A_AE_Coverage_Ownership_and_Margin_Hardening_v1.0.md`
21. `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
22. `NeX_MyBee_CP_M1_E2E_FX_01B_5A_Approved_Allocation_Plan_Semantic_Resolution_Closure_v1.0.md`
23. `NeX_MyBee_CP_M1_E2E_FX_01B_6A_EOS_Allocation_to_PnL_Projection_Activation_Boundary_v1.0.md`
24. `NeX_MyBee_CP_M1_E2E_FX_01B_6B_Installed_M1_Preparation_and_Deterministic_Plan_Activation_Closure_v1.0.md`
25. `NeX_MyBee_Post_Wave_UIUX_Compatibility_Performance_Backlog_v1.0.md`
26. `NeX_MyBee_M1_Final_AsBuilt_Baseline_and_W80_Handoff_v1.0.md`
27. `NeX_MyBee_W80_CA00_Platform_Diagnostic_Logging_and_Live_Journey_Evidence_Boundary_v1.0.md`
28. `NeX_MyBee_W80_CA00A_Playwright_Screen_Evidence_Integrity_and_Retention_Boundary_v1.0.md`
29. `NeX_MyBee_W80_CA00B_PA_WorkResult_to_IA_Business_Result_Propagation_Closure_v1.0.md`
30. `NeX_MyBee_W80_CA00C_Operational_Usability_and_Live_Journey_Experience_Hardening_v1.0.md`
31. `NeX_MyBee_W80_CA00D_MO_Capability_Scoped_Readiness_and_Healthcheck_Boundary_v1.0.md`
32. `NeX_MyBee_W80_CA00E_Cross_Agent_Semantic_Handoff_Evidence_Reuse_and_Role_Scoped_Replanning_Boundary_v1.0.md`
33. `NeX_MyBee_W80_CA00F_Sequential_Approval_Result_Publication_WA_Evidence_and_Allocation_Responsibility_Boundary_v1.0.md`
34. `NeX_MyBee_W80_CA00F_5A_Accounting_Allocation_Product_Entry_and_Domain_Intent_Activation_Closure_v1.0.md`
35. `NeX_MyBee_W80_CA00F_5B_Primary_Project_Code_Typed_Business_Context_Propagation_Closure_v1.0.md`

The Markdown Slice Plan and its Execution Matrix JSON are one planning set.
The JSON is machine-readable traceability input, not runtime configuration or
evidence that an implementation gate has passed.

W80-CA00 is the diagnostic and live-evidence amendment applied after the M1
As-Built freeze and before W80-CA01. It keeps ordinary service logs content-safe
while admitting raw prompt, AgentPlan, ExecutablePlan, API payload, and runtime
step evidence only in an explicitly enabled restricted `LIVE_JOURNEY` session.
Secrets remain forbidden, multipart/binary content remains digest-only, and no
business schema, public API, or authority boundary changes.

W80-CA00A is the screen-evidence corrective amendment. It requires each
Playwright screenshot to follow a semantic DOM assertion, records a private
hash-bound manifest, proves restart recovery on the visible owner-scoped result
surface, and moves the PNG and manifest files into the same restricted
live-journey evidence session before teardown. It adds no database migration or
backend business API.

W80-CA00B closes the product-result propagation gap exposed by W80-CA00A. It
adds a hash-bound, owner-safe business projection to the existing WC WorkResult
event and restores it through the generalized AE resume path into ordinary IA
plan finalization. It adds no table, parallel result pipeline, scenario fixture,
or public business API.

W80-CA00C hardens the installed Workspace and authority entry experience. It
adds viewport-bounded conversation scrolling, a user-facing WorkResult
presentation mapper, and a least-privilege default employee product profile.
IA, PA, human Project authority, and AE/WC/WA/OA service-principal grants remain
separate. Approval, administration, and service scopes are never defaulted to
employees or Agents, and no existing membership is silently rewritten.

W80-CA00D separates shallow NeX-MO process/database readiness from active
remote-provider admission. Protected provider health can be requested for one
capability while the no-query operations view remains compatible with the
three-provider aggregate. AE generation planning requests generation health
only, and capability-specific caches prevent unrelated embedding and reranking
traffic during generation-only journeys. No provider contract, model binding,
database schema, or business API is changed.

W80-CA00E defines the general semantic handoff between IA and a claimed PA,
CA, or EA. It preserves compatible parent WorkIntent and semantic evidence,
always rebuilds target-Agent authority context, separates delegation planning
from claimed-work execution planning, and retains a safe full-pipeline fallback.
Evidence reuse is policy- and hash-governed; authority changes and scope or hash
conflicts fail closed and cannot be repaired by a provider call. The amendment
does not optimize only the M1 scenario and introduces no fixture-specific
runtime branch.

W80-CA00F separates the post-handoff accounting responsibilities that the M1
acceptance journey intentionally combined. It preserves immutable multi-stage
approval routing while requiring business approval before accounting-stage
activation, fixes IA Workspace publication as the requester-visible result
barrier, distinguishes mandatory WA execution evidence from optional rendered
assets, and retires automatic allocation/P&L execution from Journal completion.
Journal and accounting allocation are verified by separate protected live
journeys, with no fixture-specific product branch or planned database migration.

W80-CA00F.5A closes the semantic product-entry gap discovered before the split
live acceptance. It admits `FINANCE.COST_ALLOCATION.RUN` through the generic
DomainIntentActivator registry, preserves a typed/hash-bound allocation intent
inside the common WorkIntent SoR, and enters the existing Product Coordinator,
AgentPlan, ExecutablePlan, and RuntimeJob pipeline. Fresh OA/EOS authority remains
an execution-time requirement; fixed tenants, ratios, Project counts, Plan IDs,
and fixture-driven product branches are forbidden.

W80-CA00F.5B closes the Project identity propagation gap exposed by the
installed Journal journey. New Project-scoped business contexts preserve the
canonical `primary_project_code` as typed, hash-bound input across IA, WC, and
PA, while pre-amendment v1 replay remains compatible. General Chat/RAG remains
Project-neutral; personal default scope and PA lifecycle are explicitly
deferred to a separate design decision.

The W30-CA01 pair is the source-backed post-W20 delta. It takes precedence
only for W30 entry ordering, current migration-number reservations, the
`MB3-01` wave label, and the scoped `DOCUMENT_SIGNOFF` finalization gap. It
does not rewrite the remaining v1.2 packet requirements.

W30-CA02 is the subsequent controlled amendment for Project application,
business codes, lifecycle, Project Agent synchronization, and mandatory
Project attribution in new MyBee accounting writes. Where those boundaries or
the `S3-01` migration reservation differ, W30-CA02 takes precedence over
W30-CA01 while preserving W30-CA01 as historical entry evidence.

W40-CA01 is the subsequent controlled amendment for Project applicant/owner/PM
separation, initial membership, EOS-to-OA Project-Code entitlement projection,
and fail-closed Project authorization. It preserves EOS as the Project
membership business SoR and OA as the authorization-decision SoR. Where these
authorization boundaries differ from earlier optional `project_ids` behavior,
W40-CA01 takes precedence. Its implementation and protected EOS/OA PostgreSQL
gate are mandatory before W40 `S4-01`.

W40-CA02 is the thin installed-product integration checkpoint after W40-CA01.
It does not implement GL Posting, allocation, or Project P&L. It requires the
existing W30/W40 code to run through canonical product composition, signed
service trust, actual PostgreSQL authority, durable outbox/inbox workers, and
the installed MyBee-to-EOS consumer path before W40 `S4-01` begins. A separate
final accounting product acceptance remains mandatory after Posting and
allocation are implemented.

W40-S4-00A is the final narrow pre-Posting amendment before W40 `S4-01`.
It fixes `VoucherCandidate` as the sole pre-Posting voucher authority, rejects
duplicate `journal_inbox` tables, requires returned corrections to append a
new immutable Candidate revision, and reserves `eos_journal_header/line`
exclusively for insert-only PostedJournal truth. It also supersedes obsolete
W40 references to migration number 2523, which is already occupied by the FX
market-rate adoption migration.

W50-CA01 is the source-backed allocation entry amendment after W40 closure. It
preserves mandatory approved Project Code attribution on every Journal line
while requiring an explicit, mutually exclusive `DIRECT` or
`MANAGEMENT_ALLOCATION` recognition path. It prohibits double counting the
source Project and allocated target Projects, preserves the immutable GL,
defines the `E = D + A + U` conservation boundary, and replaces occupied
historical W50 migration reservations with `2541` and `2542`. It takes
precedence only for these W50 entry semantics, migration reservations, Slice
ordering, and acceptance gates.

W60-CA01 is the source-backed Project P&L entry amendment after W50 closure.
It maps the business-facing management allocation entry to the existing
`CostSourcePool -> AllocationPlan -> AllocationBatch/Line -> Adjustment`
authorities and rejects a duplicate management-journal ledger. It defines the
privacy-preserving PayrollPostingEvidence/LaborEffortSnapshot bridge, freezes
approved actual Man-Day as the preferred payroll basis, separates
company/organization payroll expense from liability/net-pay components, and
labels plan-based fallback or residual labor explicitly. It recognizes
raw-material cost at admitted consumption rather than purchase, but requires
purchase-time Project material commitment and explicit unassigned-inventory
visibility. It separates BOM forecast, purchased/attributed inventory, and
consumed actual cost; reserves BOM as governed planning evidence; and requires
a rebuildable watermark-aware P&L projection with explicit confirmed,
committed, unassigned, provisional, unallocated, pending, and stale
classifications. It takes precedence for these W60 entry semantics and the
corrected S7-02/S7-03 boundary; NVT rollup remains S7-04/W84.

W70-CA01 is the source-backed NSL Tool and Skill-Pack entry amendment after
W60 closure. It accepts the current EOS OpenAPI and referenced schemas as the
wire authority, freezes canonical `<DOMAIN>.<BUSINESS_OBJECT>.<ACTION>` naming
for new operations, and keeps historical Golden A identities behind explicit
compatibility aliases. It separates READ, governed WRITE, approval, and
activation decisions; extends the existing immutable AE product capability
registry and NSL bundle model; and defines repository-visible D04/D12
Skill-Pack manifests, digests, OA actions, and evidence contracts. It
prohibits NSL compiler/runtime changes and new database migrations in S8-01,
and separates the S8-01 foundation Gate from the W70 M1 public E2E Gate. It
takes precedence for these W70 entry semantics while preserving all W60 GL,
authorization, Project entitlement, and payroll-privacy invariants.

W70-CA02 is the source-backed installed-runtime and staged Golden A retirement
correction discovered before the W70 public M1 E2E. It preserves the completed
Tool, Journal, signed Skill, and deterministic PA checkpoints while
distinguishing release admission from installed execution composition. Golden
A retirement is split into `CP-M1-GA-RET-01` selection freeze before
implementation and `CP-M1-GA-RET-02` active binding removal after the
generalized replacement passes protected acceptance. Between them,
`CP-M1-E2E-FX-01A` closes trusted Project resolution, IA-to-PA delegation,
claim-handoff background planning and scheduling, exact signed multi-Skill
selection, D12/D04 executor routing, and canonical OCI/Compose promotion. It
also requires registry-driven rather than M1-branch-driven composition,
authoritative runtime data origins, pre-request-only fixture use, same-OCI
acceptance, variation tests, and automated Demo/fixed-value residue checks.
Test-only orchestration and direct EOS/WC private-state shortcuts are
prohibited. The original `CP-M1-E2E-FX-01` resumes only after both `01A` and
`RET-02` pass. W70-CA02 takes precedence only for this installed-runtime gap,
Golden A active-retirement boundary, and corrected Gate ordering; it does not
change the frozen M1 business journey or authorize an NSL core change, new
business authority, or database migration by default.

CP-M1-GA-RET-02A is the post-retirement AE quality-margin work order. It keeps
the canonical AE coverage floors and complete source target unchanged while
separating active product, active compatibility, and historical-quarantine
ownership. It requires a narrow explicit many-to-many test mapping for AE
behavior whose tests use MyBee or transition filenames, prioritizes real
active planning denial and ambiguity branches, and prohibits restoring Golden
A imports or hiding active code through broad coverage exclusions. Its
corrective targets are AE statement `>= 96.25%` and branch `>= 94.50%` before
the original public M1 E2E resumes.

`CP-M1-GA-RET-02A.0` evidence is recorded in
[`mybee_phase1_w70_cp_m1_ga_ret_02a0_mixed_runtime_primitives.md`](../../slices/mybee_phase1_w70_cp_m1_ga_ret_02a0_mixed_runtime_primitives.md).
It removes the transitive active import of hash-pinned
`product_controlled_skill.py` and `golden_a_planning.py` by introducing a
scenario-neutral controlled-Skill runtime for M1. The quarantine Gate now
walks the recursive local import graph instead of checking only direct source
strings. No database migration, public API change, or remote provider was
required. The next boundary is `CP-M1-GA-RET-02A.1`.

`CP-M1-GA-RET-02A.1` evidence is recorded in
[`mybee_phase1_w70_cp_m1_ga_ret_02a1_coverage_ownership_inventory.md`](../../slices/mybee_phase1_w70_cp_m1_ga_ret_02a1_coverage_ownership_inventory.md).
It classifies all 176 AE Python modules using a semantic-hash-bound manifest,
separates ownership from canonical import reachability, and proves that the
five hash-pinned Golden A sources are absent from both the active graph and
canonical deployment inputs. Aggregate coverage scope and thresholds remain
unchanged. The next boundary is `CP-M1-GA-RET-02A.2` explicit AE test
ownership reconciliation.

`CP-M1-GA-RET-02A.2` evidence is recorded in
[`mybee_phase1_w70_cp_m1_ga_ret_02a2_explicit_ae_test_ownership.md`](../../slices/mybee_phase1_w70_cp_m1_ga_ret_02a2_explicit_ae_test_ownership.md).
It adds six exact MyBee transition tests to the AE service profile through a
separate `owned_tests` contract, preserves existing filename patterns, and
proves stable ordering, deduplication, and exclusion of historical or
domain-owned tests. It also reconciles stale v1 deployment expectations with
the current v2 generalized runtime while preserving the immutable signed
checkpoint input. The next boundary is `CP-M1-GA-RET-02A.3`.

`CP-M1-GA-RET-02A.3` evidence is recorded in
[`mybee_phase1_w70_cp_m1_ga_ret_02a3_ownership_reporting_quarantine_guard.md`](../../slices/mybee_phase1_w70_cp_m1_ga_ret_02a3_ownership_reporting_quarantine_guard.md).
It makes the ownership reporter a mandatory sixth AE Slice Gate command,
requires complete coverage reporting for all classified AE source modules,
and preserves fail-closed historical hash, recursive import and canonical
deployment quarantine checks. The integrated Gate passed with 6,225 tests,
aggregate statement/branch coverage of `96.3908% / 94.5663%`, and zero
historical conflicts. The repository Checkpoint reconciled one stale direct
consumer-composition assertion and then passed with 22,199 tests and
statement/branch coverage of `98.4001% / 96.9544%`. The next boundary is
`CP-M1-GA-RET-02A.4` active Project delegation branch hardening.

`CP-M1-GA-RET-02A.4` evidence is recorded in
[`mybee_phase1_w70_cp_m1_ga_ret_02a4_project_delegation_active_branches.md`](../../slices/mybee_phase1_w70_cp_m1_ga_ret_02a4_project_delegation_active_branches.md).
It hardens the installed Project-delegation path across capability and Project
identity mismatch, malformed WorkIntent and selectors, fresh OA denial,
retryable dependency failure, and missing, multiple or inactive Project Agent
projections. The target module now has statement and branch coverage of
`100% / 100%`; the AE Slice Gate passed at `96.4497% / 94.6630%` while
historical coverage remained unchanged. The next boundary is
`CP-M1-GA-RET-02A.5` coverage-margin closure and public M1 E2E resume decision.

`CP-M1-GA-RET-02A.5` final evidence is recorded in
[`mybee_phase1_w70_cp_m1_ga_ret_02a_ae_coverage_margin.md`](../../slices/mybee_phase1_w70_cp_m1_ga_ret_02a_ae_coverage_margin.md).
It closes the A0-A5 corrective work with all ten acceptance criteria passing,
aggregate AE statement/branch coverage of `96.4497% / 94.6630%`, active
product coverage of `97.1306% / 94.9836%`, and zero historical import or
deployment conflicts. The original `CP-M1-E2E-FX-01` public M1 E2E is admitted
to resume through the generalized installed runtime; this admission is not a
claim that the public journey itself has passed.

CP-M1-E2E-FX-01B is the source-backed transaction-orchestration correction
discovered when that public M1 E2E resumed. It freezes a typed and hash-bound
business request context, versions its WorkIntent/delegation/claimed-source
propagation, productizes proposal and VoucherCandidate preparation through
existing WC/OA/EOS APIs, materializes signed D12/D04 inputs from authoritative
service results, and connects verified Journal completion to allocation,
Project P&L, PA/WC/WA, and IA publication. It prohibits runner-owned product
transitions and adds no database migration by default. The original
`CP-M1-E2E-FX-01` remains paused until `01B.1` through `.7`, actual
PostgreSQL, live Qwen3.5-9B, authenticated Playwright, and the Repository Full
Gate pass.

CP-M1-E2E-FX-01B.5A is the source-backed allocation-plan authority correction
discovered before `.6`. It adds a side-effect-free EOS semantic resolver for
an already approved Cost Allocation Plan using exact company, source kind,
effective date, Project identity, and ratio semantics. Zero matches fail with
not-found and multiple matches fail as ambiguous; no latest-row, nearest-ratio,
fixed Plan ID, direct SQL, or release side effect is allowed. Existing Plan
and Line tables remain the SoR and no migration is allowed by default. `.6`
remains paused until the actual PostgreSQL resolution Gate binds the exact
Plan authority to the installed post-write checkpoint.

CP-M1-E2E-FX-01B.6A is the source-backed EOS projection-activation correction
discovered when `.6` reached the Allocation-to-P&L boundary. It adds the
protected `FINANCE.PROJECT_PNL.REFRESH_FROM_ALLOCATION` contract, accepts only
an AllocationBatch ID, and requires EOS to derive the verified period,
affected Projects, currency, and immutable watermark. It reuses the existing
projection store without a migration, denies cross-tenant/company and
unverified Batch requests, and requires exact replay and restart stability.
`.6` remains paused until this protected PostgreSQL Gate closes; afterward its
only admitted sequence is allocation RUN, VERIFY, P&L REFRESH, and GET.

CP-M1-E2E-FX-01B.6B is the source-backed installed-runtime correction
discovered at the `.7` entry audit. It connects an admitted M1 WorkIntent to
a capability-selected product coordinator, preserves both authoritative
approval waits as durable restart-safe checkpoints, invokes the existing
`.5` materializer only at `READY_FOR_D04`, and persists AgentPlan,
PlanValidation, and ExecutablePlan lineage before using the existing
scheduler. It prohibits fixture-driven business values, runner state
injection, provider PLAN financial authority, and semantic overloading of
existing wait/event types. No migration is authorized by default; if current
storage cannot preserve the exact semantics, implementation must stop for a
narrow persistence decision. `.7` remains paused until the actual
PostgreSQL replay, restart, approval ACK-loss, scheduling, and residue Gate
closes.

`CP-M1-E2E-FX-01B.6B.1` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b1_product_coordinator_storage_fit.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b1_product_coordinator_storage_fit.md).
It closes the generic exact-capability Product Coordinator contract and
registers M1 as `CONTRACT_ONLY`. The source-backed audit passes but records
storage fit as `NOT_FIT`: current wait registration, external event inbox,
step result, and runtime-job payload cannot preserve the two pre-plan approval
waits without changing WorkResult, NSL approval, or executable-step meaning.
`6B.2` is paused pending `CP-M1-E2E-FX-01B.6B.1A`, which must select and
authorize the smallest typed checkpoint and approval-event persistence
correction.

`CP-M1-E2E-FX-01B.6B.1A` is design-closed by
[`NeX_MyBee_CP_M1_E2E_FX_01B_6B_1A_Durable_Product_Preparation_Checkpoint_and_Approval_Event_Persistence_Decision_v1.0.md`](NeX_MyBee_CP_M1_E2E_FX_01B_6B_1A_Durable_Product_Preparation_Checkpoint_and_Approval_Event_Persistence_Decision_v1.0.md).
It selects a generic-envelope and typed-binding architecture: the existing
wait, event inbox, and `RESUME_EXECUTION` mechanics become shared runtime
primitives, while Product Preparation adds only immutable checkpoint history
and typed wait/event bindings. Existing WorkResult and NSL behavior remains
compatible and is generalized incrementally. The decision authorizes one
bounded AE migration, now delivered by `6B.1A.1`; it does not activate M1.

`CP-M1-E2E-FX-01B.6B.1A.1` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b1a1_schema_compatibility_migration.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b1a1_schema_compatibility_migration.md).
It applies migration `2517` to generalize the existing wait and event inbox,
adds only the immutable Product Preparation checkpoint and typed bindings,
and preserves existing WorkResult and NSL writers through bounded compatibility
projections. Actual `nex_ae_test` evidence covers the old and new paths,
deferred binding denial, append-only denial, and rollback zero residue. M1
remains `CONTRACT_ONLY`; generic repository APIs are assigned to `6B.1A.2`.

`CP-M1-E2E-FX-01B.6B.1A.2` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b1a2_persistence_api.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b1a2_persistence_api.md).
It adds one generalized wait/event persistence API plus immutable Product
Preparation checkpoint and typed-binding repositories over migration `2517`.
Product binding writes are atomic with the shared envelope, exact replay is
idempotent, semantic drift and incomplete lineage fail closed, and existing
WorkResult/NSL persistence remains compatible. Actual `nex_ae_test` evidence
proves rollback zero residue. Runtime matching and resume routing remain
assigned to `6B.1A.3`; M1 remains `CONTRACT_ONLY`.

`CP-M1-E2E-FX-01B.6B.1A.3` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b1a3_runtime_resume.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b1a3_runtime_resume.md).
It introduces one atomic matcher for shared wait/event envelopes, generalizes
`RESUME_EXECUTION` into explicit executable-step and Product Coordinator
targets, and resolves queued routes from persisted authority. Existing
WorkResult and NSL approval validation remains active and compatible. Product
resume jobs are reference-only, exact-replay safe, and remain queued when no
Product handler is installed; therefore M1 is still `CONTRACT_ONLY`. Actual
`nex_ae_test` restart/replay evidence proves rollback zero residue without a
new migration, queue, daemon, or worker.

`CP-M1-E2E-FX-01B.6B.1A.4` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b1a4_registration_compatibility.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b1a4_registration_compatibility.md).
It advances the immutable Product Coordinator registration and registry
contracts to schema `v2`, hash-binds the checkpoint schema, replay policy,
executor set, and exact D04/D12 Skill locks, and advances the contract-only M1
coordinator to version `1.1.0`. The locks are derived from the admitted Product
Capability Registry rather than fixture values. Existing WorkResult/NSL
behavior and migration `2517` remain compatible, actual `nex_ae_test` smoke
has zero residue, and M1 remains `CONTRACT_ONLY`. The corrective `6B.1A`
boundary is implementation-closed; the next canonical Slice is `6B.2`.

`CP-M1-E2E-FX-01B.6B.2` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b2_durable_preparation_approval_resume.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b2_durable_preparation_approval_resume.md).
It connects the registered M1 Product Coordinator to the existing proposal and
VoucherCandidate preparation adapter, persists hash-bound checkpoints for both
owner-authoritative approval waits, and reloads fresh authority at each resume.
Approval events may advance only after the shared matcher has produced a
`RESUME_EXECUTION` RuntimeJob; direct Product-specific resume is rejected.
Exact replay and ACK loss are idempotent, stale or drifted events fail closed,
and actual `nex_ae_test` shared persistence/restart evidence has zero residue.
M1 remains globally `CONTRACT_ONLY`; `READY_FOR_D04` plan persistence and
scheduling are assigned to the next canonical Slice, `6B.3`.

`CP-M1-E2E-FX-01B.6B.3` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b3_plan_persistence_scheduling.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b3_plan_persistence_scheduling.md).
It reloads the exact durable `READY_FOR_D04` checkpoint, invokes the existing
deterministic `.5` materializer, persists AgentPlan, PlanValidation, and
ExecutablePlan through their existing repositories, and calls the existing
scheduler only after all three records are durable or exactly replayed.
Provider PLAN output remains non-authoritative, semantic drift fails closed,
and crash recovery uses immutable repository replay rather than Slice-local
state. No migration, queue, worker, inbox, generic runtime branch, or remote
provider dependency was added. M1 remains globally `CONTRACT_ONLY`; the next
canonical Slice is `6B.4`, which owns the installed multi-service PostgreSQL
replay, restart, approval ACK-loss, scheduling, and zero-residue Gate.

`CP-M1-E2E-FX-01B.6B.4` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b4_protected_gate.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b4_protected_gate.md).
It runs the installed AE Product Preparation and deterministic planning
persistence over actual `nex_ae_test`, proves restart and ACK-loss convergence
at both approval waits and after plan scheduling, and combines the existing
WC, OA, and EOS owner-service PostgreSQL smokes into one protected matrix.
Cross-scope, unavailable fresh authority, stale event, and semantic drift
remain zero-mutation failures. Proposal, candidate, review, admission, plan,
RuntimeJob, and posted-journal replay do not create duplicate financial or
publication artifacts. The matrix leaves zero residue, requires no remote
provider, adds no migration, and keeps M1 `CONTRACT_ONLY`; installed process
activation remains assigned to `6B.5`.

`CP-M1-E2E-FX-01B.6B.5A` is the required controlled amendment before installed
activation. Read
[`NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_Installed_Product_Coordinator_Authority_and_Dispatch_Closure_v1.0.md`](NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_Installed_Product_Coordinator_Authority_and_Dispatch_Closure_v1.0.md)
before resuming `6B.5`. Source-backed review found that the M1 registration is
still contract-only, no installed owner-authority resolver exists, valid
step-less Product resume jobs cannot be claimed by the current dispatcher,
and public claimed-work planning bypasses Product coordination. The amendment
productizes owner-authoritative resolution, generic runtime assignment kinds,
capability-selected public routing, one installed composition factory, and
activation/readiness/rollback locks. It prohibits scenario branches, fixed
business values, a second queue or worker, and a migration by default. `01B.7`
remains suspended until the five original `6B.5A` Slices and three corrective
`.5A.3A` Slices close the protected installed Gate.

After `CP-M1-E2E-FX-01B.6B.5A.3`, read
[`NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_3A_Advisory_Product_Planning_Proposal_and_Deterministic_Execution_Boundary_v1.0.md`](NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_3A_Advisory_Product_Planning_Proposal_and_Deterministic_Execution_Boundary_v1.0.md)
before `.5A.4`. The corrective amendment makes generation-provider planning
an admitted, immutable, non-authoritative `ProductPlanningProposal`, while
Product Coordinator checkpoints and deterministic materialization remain the
only final execution authority. It also freezes explicit deterministic-only,
provider-assisted optional, and provider-assisted required policies and
prohibits registered Product work from silently falling through to direct
provider planning.

After `CP-M1-E2E-FX-01B.6B.5A.5`, read
[`NeX_MyBee_CP_M1_E2E_FX_01B_6B_5B_Installed_WC_Assignment_Dispatch_Closure_v1.0.md`](NeX_MyBee_CP_M1_E2E_FX_01B_6B_5B_Installed_WC_Assignment_Dispatch_Closure_v1.0.md)
before resuming `CP-M1-E2E-FX-01B.7`. Source-backed review found that public
delegation durably creates a WC WorkItem in `CREATED`, but the installed
topology has no generic process that invokes the existing authoritative
`CREATED -> ROUTED -> ASSIGNED` transitions. The amendment adds one WC-local
assignment dispatcher that reuses the existing routing policy, AE Agent
Registry, fresh OA authorization, coordination repository, shared JobQueue,
worker runner, and heartbeat. It keeps claim-handoff transport in the existing
WC event-delivery worker, prohibits M1/tenant/Project/fixture dispatch
branches, requires actual WC/OA/AE PostgreSQL concurrency and restart
evidence, and authorizes no migration by default. `01B.7` remains suspended
until all five `6B.5B` Slices close the installed protected Gate.

`CP-M1-E2E-FX-01B.6B.5B.1` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b1_claimable_dispatch_contract.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b1_claimable_dispatch_contract.md).
Actual PostgreSQL planning showed that the existing tenant-leading WorkItem
index could not safely serve a generic cross-tenant dispatcher scan. The
approved `1007_wc_assignment_dispatch_scan` migration adds only a partial
`CREATED/ROUTED` index. WC now exposes state-specific bounded keyset discovery
and a content-minimal, deterministic `WC_ASSIGNMENT_DISPATCH` job contract
with explicit retry, authority-reload, and terminal dispositions. No job is
enqueued or executed yet; `.5B.2` owns the generic scheduler and handler.

`CP-M1-E2E-FX-01B.6B.5B.2` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b2_scheduler_handler.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b2_scheduler_handler.md).
The WC-local scheduler now creates deterministic route and claim jobs through
the shared JobQueue, and the generic handler executes them through
`run_worker_once()` while preserving `WorkCoordinationService.route()` and
`claim()` as the only transition authority. Retry, one-time authority reload,
terminal dead-letter, route replay, and claim replay are explicit. Actual
`nex_wc_test` evidence covers route, claim, repository restart, exact replay,
and zero residue without a migration or remote provider. Installed daemon,
liveness, service-log, and dependency composition remain assigned to `.5B.3`.

`CP-M1-E2E-FX-01B.6B.5B.3` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b3_installed_process_liveness.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b3_installed_process_liveness.md).
WC now has a package-checkable and continuously runnable assignment-dispatch
process that composes the existing coordination authority, AE Agent Registry,
fresh OA authorization, shared JobQueue, heartbeat, and service-log stores.
Actual `nex_wc_test` evidence proves current migrations, one-cycle liveness,
and recovery from a route commit followed by process/engine restart before
claim. The restarted generic scan converges the WorkItem to one authoritative
Assignment and Claim without fixture transitions. Compose, OCI, healthcheck,
and installed topology activation remain assigned to `.5B.4`.

`CP-M1-E2E-FX-01B.6B.5B.4` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b4_compose_oci_topology.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b4_compose_oci_topology.md).
The assignment dispatcher is now the canonical twenty-first process and
reuses the existing non-root `nex-wc-runtime` image as a second WC entrypoint.
Compose startup is gated on healthy OpenBao, WC, AE, and OA services; protected
profiles fail closed without both assignment endpoints and signed trust edges.
Source admission, actual Compose rendering, package-isolated OCI checking, and
scenario-residue rollback guards pass without a migration or provider contact.
The owner-scoped WC image and dispatcher check pass, but the complete canonical
release-set package matrix exposes a pre-existing AE image gap: the generic AE
image does not include the admitted NSL wheel and the AE worker exits with
`ModuleNotFoundError: nsl`. Actual PostgreSQL concurrency and authoritative
claim-handoff delivery remain assigned to `.5B.5`, which is paused until a
short `.5B.4A` AE NSL packaging reconciliation restores the complete release
set.

`CP-M1-E2E-FX-01B.6B.5B.4A` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b4a_ae_nsl_wheel_packaging.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b4a_ae_nsl_wheel_packaging.md).
Only the current canonical AE artifact now targets `ae-product-runtime`; the
historical `ae-runtime` target remains available. The canonical builder admits
the locked NSL v0.2.1 wheel before Docker contact, binds the wheel bytes and
verified Product Runtime assets into the OCI context digest, preserves the
non-root boundary, and rejects wheel, Platform lock, target, package inventory,
or isolation drift. An actual AE image build and isolated worker package check
pass without database or provider contact. `.5B.5` remains gated on the final
clean-tree nine-image release-set matrix from the committed Slice revision.
That matrix subsequently passed from commit `130c173a`: all nine images are
non-root with unique manifests, all twelve background/package checks passed,
and the release set is complete. The `.5B.5` PostgreSQL and authoritative
claim-handoff Gate may therefore resume.

`CP-M1-E2E-FX-01B.6B.5B.5` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b5_protected_postgres_gate.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6b5b5_protected_postgres_gate.md).
The protected Gate applies current WC, AE, and OA migrations, creates the
WorkItem through the public WC API, and drives route and claim only through
concurrent installed assignment-dispatch processes. The first actual run found
and closed a deterministic Job enqueue race by accepting only exact immutable
job replay while rejecting semantic conflicts. The existing event-delivery
worker then delivered one signed authoritative handoff to AE; dispatcher and
delivery restart were idle, fresh OA claim denial was fail-closed, heartbeats
were persisted, and all tenant-scoped rows were removed. The actual PostgreSQL
Gate passed all 15 checks, the WC Slice Gate passed with statement `98.16%`
and branch `95.95%`, and no remote provider was contacted. The `.5B` boundary
is closed and `CP-M1-E2E-FX-01B.7` may resume with decision `GO`.

`CP-M1-E2E-FX-01B.7A` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7a_current_platform_database_closure.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7a_current_platform_database_closure.md).
It replaces the inherited seven-database migration admission on the canonical
installed path with one exact eight-database OA/AG/AE/CX/MO/WC/EOS/WA backup
and migration boundary while preserving historical P8 Demo contracts. An
actual all-eight logical backup preceded 47 admitted migrations; post-run
inspection reports eight of eight databases current with redacted evidence.
The database packaging blocker is closed and `.7` may resume its installed
product acceptance.

`CP-M1-E2E-FX-01B.7B` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7b_handoff_lease_timing.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7b_handoff_lease_timing.md).
The installed M1 journey exposed that the historical 300-second WC claim lease
could expire during synchronous Qwen3.5-9B planning retries. The corrective
boundary keeps planning-before-ACK, promotes an explicit shared 600-second
installed lease, retains the 240-second handoff timeout, rejects configuration
drift, and records each claimed delivery attempt with durable elapsed-time and
error evidence. Source and WC Slice Gates pass without a migration. The actual
DGX-backed installed journey remains required before `.7` can close.

`CP-M1-E2E-FX-01B.7C` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7c_scalar_context_candidate_repair.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7c_scalar_context_candidate_repair.md).
The same installed journey exposed a provider formatting defect where a
CONTEXT parameter value was an object or array despite the canonical
scalar-only contract. The corrective boundary keeps that contract strict and
admits only one bounded regeneration for the exact scalar-value diagnostic,
without passing the rejected output back to the provider. Dedicated Prompt
Registry provenance, immutable model/route lineage, and durable service-log
evidence make the repair observable; every other malformed, authority, or
injection response remains fail-closed. AE Slice Gate and actual
`nex_ae_test` evidence persistence/cleanup pass without a migration. The final
DGX-backed installed journey remains required before `.7` can close.

`CP-M1-E2E-FX-01B.7D` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7d_progress_timeout_hardening.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7d_progress_timeout_hardening.md).
The post-`.7C` installed run compiled and submitted transaction one but exposed
an acceptance-runner defect: its 960-second parent timeout included startup and
could terminate before the browser's 900-second result deadline produced
diagnostics. `.7D` separates 120-second UI actions from per-transaction
900-second result windows, derives a 2,220-second parent budget, emits atomic
redacted progress heartbeats, and captures bounded AE/WC operational states
before teardown. AE and Web regressions, coverage, and actual AE/WC PostgreSQL
diagnostic queries pass without a migration. The protected exact-head journey
must be rerun before `.7` can close.

`CP-M1-E2E-FX-01B.7D-A` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7da_semantic_submit_zero_residue.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7da_semantic_submit_zero_residue.md).
It separates ordinary 60-second UI actions, the Qwen3.5-9B three-stage
180-second semantic submit window, and the 900-second approval/result window.
Failure evidence now retains the original error together with structured
isolated-database cleanup results, and cleanup continues across database owners
without masking residue. Three historical acceptance schema sets were admitted
by exact naming and migration identity, removed under their owning roles, and
all eight dev databases now report zero `m1_01b7_%` residue. No migration or
public product contract changes. The exact-head live rerun admitted transaction
one's semantic submit in approximately 135 seconds and proved zero-residue
failure cleanup across all eight databases. The parent `.7` journey remains
blocked because its PA execution stayed `QUEUED:INTAKE` after the WC claim
became `ACTIVE:EXPIRED`; another live replay is not admitted before that
recovery boundary is corrected.

`CP-M1-E2E-FX-01B.7E` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7e_claim_recovery_approval_inbox.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7e_claim_recovery_approval_inbox.md).
It adds bounded recovery only for expired WC claims whose handoff is still
`PENDING/FAILED` and is not bound to an AE execution. In-flight, delivered, or
execution-bound handoffs are deliberately excluded to prevent duplicate PA
execution. Product admission now projects the durable execution as
`WAITING_APPROVAL:PLAN_BUILD`, and the M1 OA approver role is aligned with the
EOS/WC `TEAM_LEAD` approval target. Approval delivery remains the existing
`EOS -> WC SoR -> AE authenticated facade -> AE Web approval inbox` path; no
approval object is copied into an IA conversation. Actual `nex_wc_test`, WC
and AE Slice Gates, coverage, and zero-residue checks pass without a migration
or remote-provider call. One protected exact-head live replay is now admitted
after confirming DGX availability.

`CP-M1-E2E-FX-01B.7F` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7f_eos_approval_receipt_product_resume.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7f_eos_approval_receipt_product_resume.md).
It validates EOS document-signoff and accounting approval receipts as typed
authority outcomes, resolves the existing generalized Product wait by exact
tenant, authority kind, and case reference, and reuses the current Product
event persistence and `RESUME_EXECUTION` enqueue boundary. Approval, rejection,
exact replay, ACK-loss retry, restart, and cross-tenant failure semantics are
covered without a migration or scenario-specific product branch. Actual
`nex_ae_test` restart smoke and the AE Slice Gate pass; one protected exact-head
live journey remains before this corrective Slice and the parent `.7` boundary
can close.

`CP-M1-E2E-FX-01B.7G` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7g_ae_product_resume_worker_lease_budget.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7g_ae_product_resume_worker_lease_budget.md).
The `.7F` protected run proved the authority receipt and resume admission but
exposed an installed runtime-policy mismatch: the Product resume worker still
used the general 60-second RuntimeJob lease and accumulated repeated
`LEASE_EXPIRED` attempts during synchronous Qwen3.5-9B work. `.7G` preserves
the 60-second library default while explicitly admitting a bounded 600-second
canonical Product worker lease, exposes the effective value in startup
evidence, and rejects source, rendered-Compose, or deployment-audit drift. Its
exact-head protected rerun proved the 600-second policy and live provider
success, then exposed the separate missing Product RuntimeJob settlement
boundary. No migration, public API, queue, or asynchronous path is added.

`CP-M1-E2E-FX-01B.7H` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7h_product_runtime_job_settlement.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7h_product_runtime_job_settlement.md).
It makes the installed Product assignment handler the explicit settlement
authority for its existing RuntimeJob. Success is completed under the current
lease token, retryable failures use the existing bounded queue retry contract,
non-retryable failures become terminal, and stale-token completion remains
fail-closed. Plan, compiler, step, and `RESULT_VERIFY` semantics remain
unchanged. Actual `nex_ae_test` proves both approval resume jobs reach `DONE`
before the existing scheduler creates the first executable-step job. One
exact-head protected installed journey remains before `.7` closure.

`CP-M1-E2E-FX-01B.7I` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7i_primary_project_candidate_identity.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7i_primary_project_candidate_identity.md).
The post-`.7H` protected run reached Project Agent handoff but the provider
represented both the primary Project and another allocation target as entity
selectors. `.7I` promotes the active intent prompt to `v12`, adds the typed
`primary_project_code` candidate, and cross-validates it against unique Project
selectors and allocation targets. Admission retains one canonical delegation
selector without using order or confidence; unknown, duplicate, or mismatched
identity fails closed. Prompt `v11` remains replay-only and no migration or
public API widening is introduced. Actual `nex_ae_test` prompt activation and
the AE Slice Gate pass at statement `96.46%` and branch `94.72%`. The exact-head
protected journey then proved deterministic PA handoff and one delivered
BUSINESS_FORMAL approval without `PROJECT_CODE_AMBIGUOUS`. The following
Product `RESUME_EXECUTION` failed with the generic
`ae.product_coordinator_assignment_failed` reference before accounting
preparation. EOS/WC terminal binding diagnostics differ on version and target
role, but causality is not yet observable. `.7I` is closed while parent `.7`
remains blocked on a separate typed Product approval-resume corrective boundary;
all eight isolated schemas and Compose resources were removed.

The subsequent typed resume, VoucherCandidate validation, Project-scoped
accounting authorization, SoD, plan materialization, D12, and D04 corrective
boundaries are recorded in the Slice evidence set from
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7j_typed_failure_approved_document_reference.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7j_typed_failure_approved_document_reference.md)
through
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7p_installed_d04_controlled_skill_initial_diagnostics_contract_alignment.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7p_installed_d04_controlled_skill_initial_diagnostics_contract_alignment.md).
They preserve generic Product runtime contracts while aligning only the
source-backed authority, schema, Skill, Tool, and executor mismatches exposed
by exact-head protected runs.

`CP-M1-E2E-FX-01B.7Q` final closure evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b7q_result_finalization_wa_settlement.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b7q_result_finalization_wa_settlement.md).
It restores generic result continuation and IA publication, exposes bounded WA
notification outcomes, and closes a canonical Traefik route omission that had
returned HTTP 404 before WA authorization. The exact-head protected journey
then passed with two non-identical transactions, six approval decisions, two
immutable Journals, two AgentResults, four successful WA jobs and work assets,
restart-safe exactly-once evidence, live Qwen3.5-9B generation, actual eight
PostgreSQL databases, authenticated Playwright, and zero residue. The parent
`CP-M1-E2E-FX-01B.7` boundary is closed.

The original top-level `CP-M1-E2E-FX-01` M1 checkpoint is closed by
[`mybee_phase1_w70_cp_m1_e2e_fx_01_closure.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01_closure.md)
and the machine-readable redacted evidence projection at
[`cp_m1_e2e_fx_01_evidence.v1.json`](../../mybee_phase1/closure/cp_m1_e2e_fx_01_evidence.v1.json).
It adopts the exact-source `.01B.7Q` live evidence, reconciles all seven M1
checkpoints, and explicitly retains full S8-02, S8-03, MB8-01, and formal
release obligations for M2. No product runtime source, migration, or provider
call is added by the closure. The next W70 boundary is `W70-M1-GATE-01`, the
exact-head Repository Full Gate and release-set reconciliation.

`W70-M1-GATE-01` final evidence is recorded in
[`mybee_phase1_w70_m1_gate_01_exact_head_full_gate_release_set_reconciliation.md`](../../slices/mybee_phase1_w70_m1_gate_01_exact_head_full_gate_release_set_reconciliation.md).
The canonical Full Gate passes with `24,031` Python tests, repository
statement/branch coverage of `96.3353% / 95.3119%`, and product coverage of
`98.2666% / 96.7614%`. A clean-tree nine-image release set is bound to product
revision `773769bafa2ac6680d3a775f81902a2e69103909`; all nine images are
non-root, all 12 background/package checks pass, and the 18-service,
21-process Compose topology admits the same release digest without rendering
secrets or database URLs. W70 M1 is closed. The next planned boundary is W80
entry reconciliation before `S5-01` through `S5-04`.

The final W70 M1 As-Built and W80 handoff is frozen by
[`NeX_MyBee_M1_Final_AsBuilt_Baseline_and_W80_Handoff_v1.0.md`](NeX_MyBee_M1_Final_AsBuilt_Baseline_and_W80_Handoff_v1.0.md)
and its machine-readable projection
[`w70_m1_final_asbuilt_w80_handoff.v1.json`](../../mybee_phase1/closure/w70_m1_final_asbuilt_w80_handoff.v1.json).
It preserves `M1_CHECKPOINT_ONLY`, all seven accepted M1 checkpoints, 210
migrations across eight services, the exact-head Full Gate, and the canonical
nine-image release set while keeping every M2 packet explicit.
`W70 M1 FINAL AS-BUILT FROZEN`; W80 entry is authorized only through
`W80-CA01` before `S5-01` through `S5-04`.

`W70-M1-PROMOTION-01` promotion policy and acceptance evidence are recorded in
[`mybee_phase1_w70_m1_promotion_01_branch_to_master_baseline.md`](../../slices/mybee_phase1_w70_m1_promotion_01_branch_to_master_baseline.md).
The accepted MyBee source branch is a strict descendant of `master`; the
promotion must use a merge commit, preserve every Slice commit, and produce a
tree byte-identical to the source tip. Squash and rebase promotion are
forbidden. After the two-parent merge and remote verification, `master`
becomes the canonical M1 baseline and the next boundary remains `W80-CA01`.

`CP-M1-E2E-FX-01B.6A.1` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6a1_refresh_contract_source_resolver.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6a1_refresh_contract_source_resolver.md).
It closes the canonical protected contract and the mutation-free EOS source
resolver over verified Batch, Line, SourcePool, and Project authority. The
route and projector remain intentionally inactive until `.6A.2`; actual
PostgreSQL protected evidence remains assigned to `.6A.3`.

`CP-M1-E2E-FX-01B.6A.2` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6a2_projection_activation.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6a2_projection_activation.md).
It activates the protected EOS route through the existing projector and
immutable repository, previews all affected Projects before mutation, and
provides exact restart/concurrency replay semantics without a migration. The
strict AE consumer and actual PostgreSQL protected Gate remain assigned to
`.6A.3`; the parent `.6` orchestration is still paused until that Gate closes.

`CP-M1-E2E-FX-01B.6A.3` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6a3_strict_consumer_protected_gate.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6a3_strict_consumer_protected_gate.md).
It closes the strict provider-neutral consumer, installed AE composition,
signed W70 admission reconciliation, and actual `nex_eos_test` creation,
replay, restart, concurrency, scope-denial, zero-mutation, and zero-residue
Gate. The corrective `6A` boundary is closed without a migration or model
provider, and the parent `.6` orchestration is ready to resume only as
`allocation RUN -> VERIFY -> P&L REFRESH -> GET`.

`CP-M1-E2E-FX-01B.6` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01b6_result_integration.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01b6_result_integration.md).
It connects the verified Journal to generic EOS SourcePool admission,
allocation RUN/VERIFY, Batch-only P&L refresh, and authorized Project reads,
then closes redacted PA/WC results, WA evidence intake, and owner-visible IA
publication through existing product components. Actual OA/AE/WC/EOS/WA test
databases, replay, restart, authorization/privacy negatives, zero residue, and
the AE Slice Gate close the boundary without a migration or model provider.
The `.7` entry audit found that the installed path does not yet activate the
existing preparation adapter, `READY_FOR_D04` materializer, plan
persistence, and scheduler from a public-originated WorkIntent. The next
required boundary is `CP-M1-E2E-FX-01B.6B`; only its closure may resume
`CP-M1-E2E-FX-01B.7` protected public-product acceptance.

`W70-S8-01A` implementation evidence is recorded in
[`mybee_phase1_w70_s8_01a_tool_inventory.md`](../../slices/mybee_phase1_w70_s8_01a_tool_inventory.md).
It closes the canonical Tool inventory, operation identity, compatibility
alias, READ/WRITE, approval, OA action, and activation-state boundary without
activating a new Skill or changing persistence. The next W70 Slice is
`W70-S8-01B` canonical Schema/OpenAPI Tool contract admission.

`W70-S8-01B` implementation evidence is recorded in
[`mybee_phase1_w70_s8_01b_tool_contract_admission.md`](../../slices/mybee_phase1_w70_s8_01b_tool_contract_admission.md).
It admits all 18 inventory identities against exact EOS OpenAPI routes,
parameters, request bodies, successful responses, JSON Schema authorities,
OA actions, and source digests. Current status-only candidate response gaps
remain visible and fail closed for activation. No new capability, schema
authority, persistence, or runtime path is introduced. The next W70 Slice is
`W70-S8-01C` D04/D12 Skill-Pack manifest and artifact admission.

`W70-S8-01C` implementation evidence is recorded in
[`mybee_phase1_w70_s8_01c_skill_pack_manifest.md`](../../slices/mybee_phase1_w70_s8_01c_skill_pack_manifest.md).
It partitions all 18 admitted Tools into digest-pinned D04 Accounting and D12
Project descriptor-only Skill-Pack candidates. Both packs remain unsigned,
uncompiled, and runtime non-selectable; Golden A remains the only deployed
compatibility capability. The next W70 Slice is `W70-S8-01D` Product
Capability Registry and multi-bundle lock integration.

`W70-S8-01D` implementation evidence is recorded in
[`mybee_phase1_w70_s8_01d_product_capability_registry.md`](../../slices/mybee_phase1_w70_s8_01d_product_capability_registry.md).
It creates an immutable registry v2 candidate release, D04/D12 candidate
bundle locks, and a multi-bundle set while preserving the v1 Golden A runtime
selection. All 18 candidates remain non-selectable and pending S8-01E compile
and trust admission. The next W70 Slice is `W70-S8-01E` compile, admission,
alias, trust, and S8-01 Foundation Gate.

`W70-S8-01E` implementation evidence is recorded in
[`mybee_phase1_w70_s8_01e_foundation_gate.md`](../../slices/mybee_phase1_w70_s8_01e_foundation_gate.md).
It closes the S8-01 Foundation Gate against the admitted NSL v0.2.1 wheel,
records deterministic D04 READ/WRITE and D12 READ compiler profiles, rejects
status-only contracts, validates aliases and immutable registry/bundle hashes,
and proves unsigned candidate packs remain non-selectable. It does not sign or
activate a product Skill; that boundary remains owned by `CP-M1-MB8-01`. The
next W70 Slice is `CP-M1-S8-02` checkpoint-only controlled Journal execution.

`CP-M1-S8-02` implementation evidence is recorded in
[`mybee_phase1_cp_m1_s8_02_journal_controlled_write_checkpoint.md`](../../slices/mybee_phase1_cp_m1_s8_02_journal_controlled_write_checkpoint.md).
It closes the checkpoint-only EOS Journal execution, strong verification, and
typed UNKNOWN/reconciliation boundary without activating a product Skill.

`CP-M1-MB8-01` implementation evidence is recorded in
[`mybee_phase1_cp_m1_mb8_01_signed_skill_pa_orchestration.md`](../../slices/mybee_phase1_cp_m1_mb8_01_signed_skill_pa_orchestration.md).
It admits an Ed25519-signed minimal D04/D12 NSP, binds `FL0004009` and
`FL0012005`, and emits a deterministic ACTIVE Project Agent context-to-WRITE
plan. The original 18-candidate packs and canonical Compose registry remain
unpromoted. The source-backed installed-runtime gap and corrected progression
are recorded in
`NeX_MyBee_W70_CA02_Installed_PA_Delegation_and_Multi_Skill_Runtime_Composition_Closure_v1.0.md`.
The next implementation boundary is `CP-M1-GA-RET-01`, followed by
`CP-M1-E2E-FX-01A`, `CP-M1-GA-RET-02`, and finally the original
`CP-M1-E2E-FX-01` protected public M1 acceptance.

`CP-M1-GA-RET-01` implementation evidence is recorded in
[`mybee_phase1_w70_cp_m1_ga_ret_01.md`](../../slices/mybee_phase1_w70_cp_m1_ga_ret_01.md).
It closes new Golden A public selection, preserves replay-only and bounded
rollback assets, classifies the repository references, and proves actual AE
PostgreSQL has no remaining in-flight Golden A execution or runnable job. The
next implementation boundary is `CP-M1-E2E-FX-01A.1`.

`CP-M1-E2E-FX-01A.1` evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01a1.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01a1.md).
It freezes the pre-change installed composition, authoritative data-origin
matrix, and Golden/Demo residue baseline without adding a database migration.
The next boundary is `CP-M1-E2E-FX-01A.2`.

`CP-M1-E2E-FX-01A.2` evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01a2.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01a2.md).
It closes the registry-selected IA delegation planning profile and requires
EOS active Project resolution, fresh OA Project entitlement, and one active AE
Project Agent before a Project UUID can enter `DELEGATE_WORK`. IA remains
Project-neutral and no database migration was added. The next boundary is
`CP-M1-E2E-FX-01A.3`.

`CP-M1-E2E-FX-01A.3` evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01a3.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01a3.md).
It composes WC claim admission, background semantic planning, durable plan
persistence, and first-step scheduling into the installed AE handoff route.
The API acknowledges only after scheduling succeeds; replay reuses the same
execution, deterministic plan IDs, and JobQueue dedup key. No migration or
parallel runtime queue was added. The next boundary is
`CP-M1-E2E-FX-01A.4`.

`CP-M1-E2E-FX-01A.4` evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01a4.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01a4.md).
It admits a generic verified multi-Skill catalog, exact capability-to-Skill
selection, and MyBee-owned D04/D12 operation adapters. The immutable admission
lock is reconstructed from the signed NSP and Product Capability Registry in
regression, while generic runtime code remains free of MyBee capability IDs.
No migration or remote provider was added. The next boundary is
`CP-M1-E2E-FX-01A.5`.

`CP-M1-E2E-FX-01A.5` evidence is recorded in
[`mybee_phase1_w70_cp_m1_e2e_fx_01a5.md`](../../slices/mybee_phase1_w70_cp_m1_e2e_fx_01a5.md).
It promotes the exact signed M1 D12/D04 release into the canonical AE Agent
Runtime OCI/Compose composition, keeps private NSL imports behind the shared
runtime adapter, and verifies the actual `nex_ae_test` artifact persistence and
replay boundary with zero residue. Golden A is retained only as bounded
rollback until `CP-M1-GA-RET-02`; it is not an active selector. No migration or
remote provider was added. The next boundary is `CP-M1-GA-RET-02`.

`CP-M1-GA-RET-02` evidence is recorded in
`docs/slices/mybee_phase1_w70_cp_m1_ga_ret_02.md`. The canonical MyBee M1
registry, runtime admission, activation, prompt, Compose, and OCI inputs now
select only the generalized D04/D12 release. Golden A scenario assets remain
hash-pinned offline history and are absent from the active import graph and
image. The bounded Golden rollback is replaced by the last admitted
generalized M1 release. No migration or remote provider was required. The next
boundary returns to `CP-M1-E2E-FX-01`.

The Post-Wave UI/UX backlog records non-blocking TestClient compatibility and
frontend bundle-performance findings from the post-S7-01 Repository Full Gate.
It does not change the active accounting Wave or authorize immediate UI work.
Its entry condition is completion of the currently planned functional Waves,
after which the items require a separate corrective Slice and a new clean Full
Gate baseline.

Runtime implementation evidence for the W30-CA02 Project foundation is
recorded in
[`mybee_phase1_w30_project_foundation_checkpoint.md`](../../slices/mybee_phase1_w30_project_foundation_checkpoint.md).
That Checkpoint closes `W30-S00A` through `W30-S00D-A` and opens `S3-01`.
It does not claim completion of the full W30 Wave, which still includes
`S3-01` through `S3-03` and `MB3-01` under the active Slice Plan.

`S3-01` implementation evidence is recorded in
[`mybee_phase1_s3_01_voucher_candidate_v2.md`](../../slices/mybee_phase1_s3_01_voucher_candidate_v2.md).
It closes the proof-bound Project-specific VoucherCandidate v2 header,
immutable revision/line persistence, command/API, replay, and actual EOS
PostgreSQL boundary.

`S3-02` and `S3-03` implementation evidence is recorded in
[`mybee_phase1_s3_02_candidate_accounting_fx_period_balance_validation.md`](../../slices/mybee_phase1_s3_02_candidate_accounting_fx_period_balance_validation.md)
and
[`mybee_phase1_s3_03_candidate_review_state_machine.md`](../../slices/mybee_phase1_s3_03_candidate_review_state_machine.md).
Together they close authoritative accounting/FX/period/balance validation and
the durable Submit/Return/Invalidate review state machine.

`MB3-01` implementation and W30 closure evidence is recorded in
[`mybee_phase1_mb3_01_voucher_candidate_consumer.md`](../../slices/mybee_phase1_mb3_01_voucher_candidate_consumer.md).
It closes the MyBee-owned provider consumer for create, validate,
BUSINESS_FORMAL review submission, and review projection while preserving EOS
as the persistence owner and prohibiting direct GL writes. The next planned
entry after the W30 Full Gate is W40 `S4-01`.

### COA Follow-up Reading Order

Read the post-S1-02 standard Chart of Accounts design set in this order:

1. `NeX_MyBee_COA_PAD_v1.0.md` — the base COA design authority.
2. `NeX_MyBee_COA_CA01_v1.0.md` — takes precedence over the COA PAD v1.0
   **only** for the unified GLOBAL/TENANT Codebook structure and its related
   publication/read contracts. All other PAD and SRS invariants remain in
   force.
3. `NeX_MyBee_COA_Codebook_Candidate_v0.1.json` — accounting-review data only;
   it is not an approved operational seed. Its
   `status=DESIGN_CANDIDATE_NOT_APPROVED` and `runtime_seed_allowed=false`
   boundaries must remain fail-closed until exact-row accounting approval.
4. `NeX_MyBee_COA_CA01_Decision_Delta_v1.0.json` — machine-readable evidence
   of the CA01 decision delta, Codex implementation changes, and required
   validation gates. It is not runtime configuration or proof that those gates
   have passed.
5. `NeX_MyBee_COA01_Candidate_Reviewer_Diff_v1.0.md` — COA-01's hash-bound
   88-leaf human review baseline. Structural validation has passed, but the
   original Candidate remains an immutable pre-approval snapshot. Section 4
   records the later COA-01A approval overlay and its exact limitations.

COA-01A machine-readable admission artifacts are read in this order:

1. `domains/mybee/config/account_catalog/product_accounting_approval.v1.json`
2. `domains/mybee/config/account_catalog/approved_standard_chart.v1.json`
3. `domains/mybee/config/account_catalog/approved_seed_manifest.json`

The approval is source admission only. EOS publication, OA publisher
authorization and Company adoption remain separate later gates.

The COA follow-up set preserves the completed S1-02 framework and does not
activate S1-03. It also does not authorize invented K-IFRS account numbers,
candidate seed import, or mutation of existing `eos_account`, company policy,
PostingRule, Golden A, or historical Journal semantics.

## Authority And Status

```text
Frozen NeX Platform v2.1 / Agent v2.1 / admitted NSL contracts
  > EOS canonical business contracts
  > MyBee D04/D12 PAD and SRS
  > Phase-1 in-repository ADR and ownership override
  > CA01 document-consistency closure
  > v1.2 Slice Plan and Execution Matrix
```

Current implementation-entry planning baseline:

```text
NeX repository = nurigitdev/2607_nex_platform
recorded branch = master
recorded commit = 5e64fb1f6b9af2198797d1bcdbc82e577b098fbe
implementation = NOT STARTED by this document set
```

The earlier `c2c03b20e22691cc1984f044e0cacd5d698f9bd3` references are retained
source-audit snapshots. They are historical evidence, not the current coding
entry revision. The implementation entry Slice must refresh repository HEAD,
database migration inventory, dependency revisions, and source hashes before
changing code.

## Canonical Naming

All active Phase-1 artifact filenames use the `NeX_` prefix. In particular,
the canonical SRS filename is:

```text
NeX_MyBee_D04_D12_EOS_SRS_v1.0.md
```

Historical documents may contain the former unprefixed SRS name. Those
references are preserved inside `HISTORY/` as immutable provenance and do not
create a second active SRS.

## History

The following inputs are retained under `HISTORY/` and are not active
implementation instructions:

1. `NeX_MyBee_D04_D12_EOS_Implementation_Slice_Plan_v1.0.md`
2. `NeX_MyBee_D04_D12_EOS_Implementation_Slice_Plan_v1.1.md`
3. `NeX_MyBee_D04_D12_EOS_ISP_v1.1_Repository_Ownership_Matrix.json`

The v1.2 Plan supersedes v1.1 only for repository placement, PR chronology,
and M1/M2 execution gating. Original packet IDs, SRS traceability, and
acceptance obligations remain preserved.

## Open Entry Gates

The following are deliberately not claimed as complete:

- D04/D12 source PDF page-level reconciliation and owner sign-off
- current HEAD and migration-number refresh
- actual PostgreSQL migration, concurrency, and fault acceptance
- public API, Playwright, and end-to-end execution
- accounting, tax, foreign-exchange, and release-owner approval

`Accounting Transaction Contract Closure v1.0-RC1` therefore remains a
conditional closure. A final document may be issued only after its open gates
are satisfied.
