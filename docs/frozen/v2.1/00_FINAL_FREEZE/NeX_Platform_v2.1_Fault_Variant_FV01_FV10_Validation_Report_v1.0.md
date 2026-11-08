# NeX Platform v2.1 ↔ Agent v2.1 ↔ NSL v0.2
# Fault Variant FV-01 ~ FV-10 Validation Report v1.0

**Validation Baseline**
- Platform: `NeX_Platform_v2.1_Final_Consistency_Closure_Working_Set_v1.7`
- Semantic Authority: NeX Agent v2.1 Final Frozen + NSL v0.2 Final Frozen
- Integration Authority: `NeX_Agent_v2.1_NSL_v0.2_Integration_Contract_v1.0`
- Validation Specification: `Integrated E2E Validation Plan v1.0`
- Level: Architecture / Contract validation; not source-code runtime/performance testing

## 1. Baseline Integrity

- Platform v1.7 `SHA256SUMS_FINAL_v1.7.txt`: **259 / 259 PASS**
- Platform-bundled Agent↔NSL Integration Contract vs Frozen baseline: **byte-for-byte identical**
- Platform-bundled Final Freeze Declaration vs Frozen baseline: **byte-for-byte identical**
- Frozen Agent v2.1 semantics changed: **NO**
- Frozen NSL v0.2 semantics changed: **NO**

## 2. Fault Variant Result Matrix

| FV | Scenario | Expected invariant | Principal contract evidence | Probe / Trace | Result |
|---|---|---|---|---|---|
| FV-01 | Unauthorized Approver | OA DENY → decision persistence denied → Resume=0 | `approval-decision-v2.1`: `authorized_by_oa = const true`, non-null `oa_decision_ref`; PRD38 AUTH/EVT requirements | `authorized_by_oa=false` schema rejected | **PASS** |
| FV-02 | Approval Replay / Hash Mismatch | ApprovalRequestId / BusinessOperationId / PayloadHash / WriteIntentHash mismatch → WRITE=0 | `validate_nsl_resume_binding()` + PRD38 NSL fault suite | all four independent mismatch probes return false | **PASS** |
| FV-03 | Package Revoked after Plan | execution-time current package governance/trust → BLOCK | Artifact Gateway runtime `resolve_verified`; `ArtifactAdmissionDecision`; AE `NEX-AE-NSL-FR-007` | `REVOKED + ADMITTED` schema rejected | **PASS** |
| FV-04 | Kill-switch after WAIT | Resume preflight current kill-switch → BLOCK | `NEX-REL-WAIT-FR-007`; `NEX-TST-SEC-FR-003`; `NEX-TST-FLT-FR-008`; Frozen Agent Resume current-control invariant | WAIT Resume must rebuild current OA/Role/Capability/Skill/Policy/KillSwitch before RUNNING | **PASS** |
| FV-05 | Duplicate Approval Decision Event | one active wait → one Resume Job | `NEX-REL-WAIT-FR-005/006`; RuntimeJob `UNIQUE(tenant_id,dedup_key)`; `RESUME_EXECUTION` requires `wait_id`; PRD38 T38-11 | duplicate event consumed through stable wait/resume identity and unique RuntimeJob dedup | **PASS** |
| FV-06 | Duplicate Schedule Scanner | one nominal occurrence → one occurrence → one WorkItem | `wc_schedule_occurrence UNIQUE(tenant_id,schedule_id,nominal_time)`; materialization PK by occurrence; unique WorkItem | uniqueness constraints verified | **PASS** |
| FV-07 | Schedule Misfire | SKIP / CATCH_UP / LATEST_ONLY deterministic | Schedule v1.7 time hardening: CRON5/IANA/DST/UTC nominal instant + exact misfire enum | exact enum and deterministic time semantics verified | **PASS** |
| FV-08 | Tenant Mismatch | cross-tenant reference → fail closed | OA/Security/CX/AE tenant boundary rules; tenant-bound schemas; E2E-12 tenant-negative test | NSL approval resume tenant mismatch returns false | **PASS** |
| FV-09 | CX Authority Changed | old evidence context never overrides current OA/execute authorization | CX Evidence Context = bounded input, not Authority/AgentContext SoR; authority_hash/policy_version; PRD40 current-permission revalidation; Frozen Agent protected-step current OA | stale/old evidence remains provenance only; current OA/execute authorization wins | **PASS** |
| FV-10 | Publication ACK Lost | publication retry/reconcile only; Business WRITE count=1 | ResultDelivery UNKNOWN_DELIVERY + PublicationReconciliation; TST-E11-01/03 | UNKNOWN_DELIVERY without reconciliation ref rejected; with ref valid; WRITE retry remains prohibited | **PASS** |

## 3. Negative / Structural Probe Summary

The following explicit contract probes were executed against v1.7 normative contracts.

- FV-01: Authorized approval valid / unauthorized approval invalid — **2/2 PASS**
- FV-02: baseline + ApprovalRequestId / BusinessOperationId / PayloadHash / WriteIntentHash mismatch — **5/5 PASS**
- FV-03: ACTIVE+ADMITTED valid / REVOKED+ADMITTED invalid — **2/2 PASS**
- FV-05: RuntimeJob dedup uniqueness; RESUME requires wait_id — **3/3 PASS**
- FV-06: occurrence nominal uniqueness; occurrence materialization identity; WorkItem uniqueness — **3/3 PASS**
- FV-07: exact misfire enum; deterministic time-semantics contract — **2/2 PASS**
- FV-08: cross-tenant NSL approval-resume binding — **1/1 PASS (fail-closed)**
- FV-10: UNKNOWN_DELIVERY requires publication reconciliation reference — **2/2 PASS**

Architecture-level current-control checks for FV-04 and FV-09 are normative MUST boundaries rather than pure JSON-schema predicates and were traced across Agent/Platform contracts.

## 4. Fault Variant Detailed Conclusions

### FV-01 Unauthorized Approver — PASS
A human decision cannot become a canonical `ApprovalDecision` unless current OA authorization has succeeded. The approval decision contract requires `authorized_by_oa=true` and an OA decision reference. The WC/Approval design further states that persistence and `APPROVAL_DECIDED` publication occur only after current OA approver authorization. Therefore OA DENY produces no valid decision event and no Resume trigger.

### FV-02 Approval Replay / Hash Mismatch — PASS
NSL resume binding compares TenantId, NSLExecutionId, BusinessOperationId, ApprovalRequestId, PayloadHash and WriteIntentHash against the frozen write/checkpoint state. Independent mutation of the four validation-plan keys causes the binding validator to return false, so Provider WRITE remains zero.

### FV-03 Package Revoked after Plan — PASS
Compile/plan-time selection is not execution authority. The Skill Artifact Gateway resolves and admits the exact package at runtime using current package/publisher/signing-key governance. `REVOKED`, `SUSPENDED` and `REVALIDATION_REQUIRED` cannot produce an admitted artifact. A stale plan therefore cannot force a revoked package into NSL execution.

### FV-04 Kill-switch after WAIT — PASS
Resume is a new protected-control boundary. Platform reliability and Frozen Agent contracts require current OA/EAC/PDP, RoleBinding, Capability, Skill/Policy and KillSwitch re-evaluation before transition back to RUNNING. Historical approval/checkpoint state is not authorization. Active kill-switch therefore blocks Resume/protected side effect.

### FV-05 Duplicate Approval Decision Event — PASS
The required transaction boundary is Event match → Wait SATISFIED → Resume RuntimeJob enqueue. Resume dedup uses stable execution/checkpoint/wait identity, RuntimeJob persistence has tenant-scoped dedup uniqueness, and `RESUME_EXECUTION` requires a wait reference. Duplicate approval events therefore converge on one Resume Job for the active wait generation.

### FV-06 Duplicate Schedule Scanner — PASS
v1.7 Schedule hardening provides tenant+schedule+nominal-time occurrence uniqueness and tenant+occurrence materialization uniqueness. The same semantic occurrence cannot create a second materialized WorkItem. Scanner/lease duplication is coordination retry, not new business recurrence identity.

### FV-07 Schedule Misfire — PASS
The time model is fixed to `WC_SCHEDULE_TIME_V1`: CRON5/IANA timezone, explicit DST gap/overlap rules and UTC nominal instants. Misfire vocabulary is exactly SKIP/CATCH_UP/LATEST_ONLY, so the missed-occurrence set and selected behavior are deterministic at contract level.

### FV-08 Tenant Mismatch — PASS
TenantId is an independent hard partition, not Org/Project scope. Resume and security-sensitive references carry tenant binding and mismatch fails closed. A direct negative probe of NSL approval resume with different bridge/evidence tenants returned false.

### FV-09 CX Authority Changed — PASS
CX evidence objects contain the authority hash/policy version under which evidence was retrieved, but CX Evidence Context is explicitly not the AgentContext or authorization SoR. Current OA/PDP is re-evaluated for protected execution, follow-up, preview/export and publication. Old evidence remains provenance and cannot grant authority after RoleBinding/scope/policy changes.

### FV-10 Publication ACK Lost — PASS
Business commit and result delivery remain separate failure domains. UNKNOWN_DELIVERY requires publication-specific reconciliation, and the Platform Step-5 contract prohibits converting publication uncertainty into NSL/Business WRITE retry. Business WRITE count therefore remains one.

## 5. Issue Classification

```text
FV E2E-P0  = 0
FV E2E-P1  = 0
FV E2E-PCG = 0
FV E2E-P2  = 0
```

No new Controlled Amendment is required from FV-01 ~ FV-10 validation.

## 6. Overall Result

> **FV-01 ~ FV-10 REQUIRED FAULT VARIANTS — CLOSED / PASS**

This closes Validation Plan Step 7 at Architecture/Contract level.

The next plan step is:

```text
Step 8 — Issue Consolidation / Independent Re-check
Step 9 — Final Freeze Decision
```

Before final freeze, Step 8 should independently re-check that:
1. E2E-01 ~ E2E-12 remain PASS on the current v1.7 baseline.
2. FV-01 ~ FV-10 remain PASS after consolidation.
3. E2E-P0/P1/PCG remain zero.
4. Frozen Agent v2.1 / NSL v0.2 semantics remain byte-identical.
5. SoR, identity, approval-domain, retry/reconciliation, schedule and publication invariants have no cross-document regression.
