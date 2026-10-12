# NeX Platform v2.1 ↔ Agent v2.1 ↔ NSL v0.2
# PASS E1 Contract Hardening Closure & Re-validation v1.1

**상태:** PASS — PASS E1 CLOSED  
**기준:** Integrated E2E Validation Plan v1.0  
**이전 상태:** CONDITIONAL PASS (`E2E-P1=2`, `E2E-PCG=2`)  
**수정 범위:** machine-readable contract hardening only; Frozen Agent v2.1 / NSL v0.2 semantic 변경 없음

---

# 1. Closure Summary

E1에서 발견된 4건을 모두 보완하였다.

```text
E2E-P1-01  PA project_id nullability                 CLOSED
E2E-P1-02  WC AGENT candidate discriminator          CLOSED
E2E-PCG-01 WC Claim → AE CLAIMED_WORKITEM bridge     CLOSED
E2E-PCG-02 one ACTIVE PA per tenant/project          CLOSED
```

재검증 결과:

```text
E1 Core Gate PASS = 8 / 8

E2E-P0  = 0
E2E-P1  = 0
E2E-PCG = 0
```

> **PASS E1 — CLOSED / PASS**

---

# 2. Contract Hardening Applied

## 2.1 AgentIdentity v2.1

PA branch:

```text
agent_type = PA
→ project_id required
→ project_id = non-null string, minLength 1
```

## 2.2 RoutingDecision v2.1

```text
candidate_type = AGENT
→ agent_type required
→ CA | PA | EA
```

## 2.3 WC Claim → AE Trigger Bridge

Added:

```text
WC ClaimExecutionHandoff v2.1
        ↓
AE ExecutionTrigger v2.1
source_type = CLAIMED_WORKITEM
```

Bridge preserves:

```text
tenant_id
work_item_ref
claim_ref
claim_generation
claimant/agent identity
agent_type
project_id
assignment_ref
correlation_id
causation_id
```

The handoff is valid only after successful atomic claim and assignment materialization.

## 2.4 Agent Registry PA Uniqueness

Added reference persistence/service contract:

```text
CHECK:
PA → project_id IS NOT NULL

UNIQUE ACTIVE PA:
(tenant_id, project_id)
WHERE agent_type='PA' AND status='ACTIVE'
```

Agent Registry service must return deterministic conflict if another ACTIVE PA already exists.

---

# 3. Document Back-propagation

The exact hardened contracts were back-propagated to:

```text
04 Platform SRS
14 WC SRS
15 WC Detailed Design
29 AE SRS / Detailed Design
```

The documents now explicitly reference:

```text
ExecutionTrigger v2.1
ClaimExecutionHandoff v2.1
non-null PA project_id
one ACTIVE PA per tenant/project persistence/service invariant
```

---

# 4. Re-validation Gate

| Gate | Verdict | Evidence |
|---|---|---|
| E1-G01 — TenantId explicit | **PASS** | Unchanged; EAC/Agent/WC/NSL contracts require tenant_id. |
| E1-G02 — TenantId != OrgScope != ProjectScope | **PASS** | Unchanged; tenant remains explicit first-class identity. |
| E1-G03 — Principal != Business Actor | **PASS** | Unchanged; OA EAC requires separate identities. |
| E1-G04 — AgentIdentity SoR = AE Agent Registry | **PASS** | Agent Registry persistence/service contract now added and identity schema hardened. |
| E1-G05 — WorkItem / Claim SoR = WC | **PASS** | WC remains work/claim owner; exact ClaimExecutionHandoff added. |
| E1-G06 — Current authorization SoR = OA | **PASS** | Unchanged. |
| E1-G07 — Background Agent starts only after successful Claim | **PASS** | WC ClaimExecutionHandoff v2.1 → AE ExecutionTrigger v2.1(CLAIMED_WORKITEM) now machine-readable. |
| E1-G08 — PA project 1:1 logical identity preserved | **PASS** | PA non-null project_id + partial unique ACTIVE PA index per tenant/project + service invariant. |

---

# 5. Actual Contract Probe Result

- **R-P01** — Valid PA identity: **PASS**
- **R-P02** — PA project_id=null rejected: **PASS**
- **R-P03** — PA missing project_id rejected: **PASS**
- **R-P04** — AGENT candidate with PA type accepted: **PASS**
- **R-P05** — AGENT candidate with null agent_type rejected: **PASS**
- **R-P06** — AGENT candidate missing agent_type rejected: **PASS**
- **R-P07** — PROMPT IA trigger accepted: **PASS**
- **R-P08** — CLAIMED_WORKITEM PA trigger accepted: **PASS**
- **R-P09** — Claim trigger missing claim_ref rejected: **PASS**
- **R-P10** — Claim trigger with IA rejected: **PASS**
- **R-P11** — WC ClaimExecutionHandoff accepted: **PASS**
- **R-P12** — PA uniqueness partial index present: **PASS**
- **R-P13** — PA non-null project check present: **PASS**

All probes passed.

---

# 6. Authority / Identity Chain after Closure

```text
TenantId
→ OA EAC
→ AgentIdentityRef
→ AE Agent Registry
→ WC WorkItem
→ Atomic Claim
→ Assignment Materialization
→ WC ClaimExecutionHandoff
→ AE ExecutionTrigger(CLAIMED_WORKITEM)
→ AgentExecution
→ ExecutableStep
→ BusinessOperationId
→ NSLExecutionId
```

No duplicate SoR was introduced.

---

# 7. Verdict

> **PASS E1 — AUTHORITY / IDENTITY CHAIN CLOSED**

The Integrated E2E Validation may proceed to the next planned group:

```text
E2E-01 — IA READ
E2E-04 — CA Delegation
E2E-05 — PA Project Work
```

No Final Freeze blocker remains from PASS E1.
