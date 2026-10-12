# NeX Agent v2.1 ↔ NSL v0.2 Unified Integration Change Ledger v1.0

**상태:** CONTROLLED AMENDMENT LEDGER  
**기준:** Final Architecture Consistency Review v1.0 + Integration Contract v1.0  
**NSL v0.2:** FROZEN / NO CHANGE

# 1. Change Packages

| ID | Severity | Change | Primary Docs |
|---|---|---|---|
| CCP-01 | P0 | Approval / Suspension / Resume | A01/A05/A06/A07/A10/A99 |
| CCP-02 | P1/ICG | Invocation / Identity / Context | A05/A06/A10/A99 |
| CCP-03 | P0 | Idempotency / Retry / Reconciliation | A05/A06/A07/A10/A99 |
| CCP-04 | P0 | OA / EA-Trust / Actual WRITE binding | A05/A06/A07/A10/A99 |
| CCP-05 | ICG | Verified Artifact Admission | A05/A06/A10/A99 |
| CCP-06 | P1/ICG | Result / Evidence / Audit | A06/A07/A08/A09/A10/A99 |
| CCP-07 | P1 | Baseline / Terminology | A99 + affected docs |

# 2. CHG-01 NSL WRITE Approval Ownership

- NSL WRITE Approval semantic owner = NSL
- workflow/UI/event/resume = Agent/Platform
- FORMAL_APPROVAL must not substitute NSL Approval
- Add `NSL_APPROVAL` Wait source

Acceptance:
```text
GS-02, GS-03 PASS
Provider WRITE before Approval = 0
```

# 3. CHG-02 SkillExecutionRequest

Rename Agent `ExecutionContext v1` integration DTO to `SkillExecutionRequest v1`.

Define exact fields and mapping to:
```text
VerifiedSkillArtifact + NSL ExecutionRequest + RuntimePorts
```

Acceptance:
```text
AgentExecutionId != NSLExecutionId
Tenant explicit
AgentContext full-copy absent
```

# 4. CHG-03 Idempotency Ownership

- Agent owns BusinessOperationId
- NSL Runtime owns actual WRITE IdempotencyKey
- remove/redefine LOCAL_SKILL `idempotency_key_ref`
- retry keeps BusinessOperationId

Acceptance:
```text
GS-08 + GS-08-F1 PASS
```

# 5. CHG-04 ProtectedOperationDescriptor

Add typed descriptor for EA-Trust binding.

Provider WRITE path:
```text
GovernedWriteExecutionPort
→ actual WriteCallRequest conforms_to descriptor
```

Acceptance:
```text
GS-06-F1 mismatch → WRITE=0
```

# 6. CHG-05 Artifact Admission

```text
exact skill/version
→ Signed NSP verify
→ VerifiedSkillArtifact
→ NSL
```

Acceptance:
```text
GS-02-F1 invalid package trust → BLOCK
```

# 7. CHG-06 Result Mapping

Add typed `NSLResultSummary` and exact mapper.

Acceptance:
```text
COMMITTED + Verification FAILED → no WRITE retry
UNKNOWN_COMMIT → RECONCILIATION_REQUIRED
WAITING_FOR_APPROVAL → WAITING
```

# 8. CHG-07 Evidence/Audit Projection

- NSL detailed evidence remains NSL SoR
- Agent stores refs/hashes/semantic summaries
- E2E trace chain standardized

# 9. CHG-08 A99 Reference Alignment

Update A99 referenced design versions to current Frozen set.

# 10. Amendment Order

```text
A05
→ A06
→ A07
→ A01
→ A08
→ A09
→ A10
→ A99
```

# 11. Freeze Gate

```text
Agent 12-doc consistency PASS
Golden 10 PASS
Fault variants PASS
P0=0
P1=0
ICG=0
```
