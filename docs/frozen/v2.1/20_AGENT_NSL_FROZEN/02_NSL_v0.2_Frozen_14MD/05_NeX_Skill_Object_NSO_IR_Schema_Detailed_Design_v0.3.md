# NeX Skill Object (.nso)
## Intermediate Representation Schema Detailed Design v0.3 — NSL v0.2 / IR 1.1

**문서 버전:** v0.3 — Closure Aligned  
**작성일:** 2026-08-23  
**대상 Language:** NSL v0.2  
**실제 IR Version:** `1.1`  
**Encoding:** Canonical JSON  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 0. 개정 이력

| 문서 | 내용 |
|---|---|
| v0.1 | Typed IR 기본 구조 |
| v0.2 | include/Bool/Strict CHECK/Source Bundle Hash |
| v0.3 | APPROVAL/WRITE/Write Static Analysis 추가, IR 1.1 |
| v0.3 — Closure Aligned | Signed NSP Trust Boundary 재사용, IR/Package hash ownership 분리, exact Approval↔WRITE 1:1 및 v0.1 canonical compatibility 반영 |

---

# 1. 목적

IR 1.1은 IR 1.0의 READ-only Execution Contract를 유지하면서 Controlled Write를 **Additive Extension**으로 확장한다.

```text
IR 1.0
READ / LET / FOREACH / CHECK / EMIT

IR 1.1
+
APPROVAL
WRITE
Write Safety Analysis
```

Production WRITE의 Authenticity는 IR 내부에 별도 Signature 체계를 중복 도입하지 않고 기존 **Signed NSP → Verified Package Trust Boundary**를 재사용한다.

또한 Runtime execution instance에서 생성되는 다음 값은 Static IR Schema에 포함하지 않는다.

```text
BusinessOperationId
ApprovalRequestId
IdempotencyKey
PayloadHash
PolicyDecision
CommitState
VerificationStatus
Checkpoint State
```

IR은 Skill의 deterministic static execution semantics만 표현한다.

---

# 2. Top-Level Schema

IR 1.1의 Top-Level Shape는 IR 1.0을 깨지 않는 additive form을 유지한다.

```json
{
  "format": "NSO",
  "ir_version": "1.1",
  "language": {
    "name": "NSL",
    "version": "0.2"
  },
  "skill": {},
  "semantics_profile": "NSL-0.2-STRICT",
  "features": [],
  "types": {},
  "symbols": {},
  "requires": [],
  "limits": {},
  "inputs": [],
  "contexts": [],
  "output": {},
  "body": [],
  "analysis": {},
  "hashes": {},
  "build": {},
  "debug": {}
}
```

중요한 backward compatibility rule:

```text
format = "NSO"
```

는 v0.1 canonical value를 그대로 유지한다. v0.2에서 소문자 `"nso"`로 변경하지 않는다.

IR 1.1은 새로운 APPROVAL/WRITE 관련 field를 additive하게 추가하되 기존 IR 1.0 field의 의미·shape·canonical ordering을 임의 변경하지 않는다.

---

# 3. Feature Declaration

예:

```json
{
  "features": [
    "READ",
    "CHECK",
    "APPROVAL",
    "WRITE"
  ]
}
```

Source Language Version과 IR Version mapping은 deterministic하게 고정한다.

```text
NSL 0.1 → IR 1.0
NSL 0.2 → IR 1.1
```

따라서 write-less NSL 0.2 Skill도 IR 1.1을 생성한다.

NSL 0.1 Source는 v0.2 Compiler에서도 IR 1.0과 기존 feature/canonical representation을 유지해야 하며, v0.2 keyword/feature 추가 때문에 기존 SemanticHash가 불필요하게 변해서는 안 된다.

---

# 4. RequiredTool

```json
{
  "tool_ref": "tool0003",
  "tool_id": "FINANCE.CREATE_VOUCHER_DRAFT",
  "version": "1.0.0",
  "capability": "WRITE",
  "risk_level": "R3",
  "contract_hash": "sha256:..."
}
```

`RequiredTool`은 canonical Tool Contract의 static semantic fingerprint를 표현한다.

Tool Binding 정보, runtime endpoint, credential, Tenant/User entitlement, MFA, network policy 등은 포함하지 않는다.

또한 다음 runtime invocation identity는 RequiredTool에 포함하지 않는다.

```text
BusinessOperationId
IdempotencyKey
PayloadHash
ApprovalRequestId
```

---

# 5. ApprovalStatement Node

```json
{
  "kind": "approval",
  "node_id": "approval0001",
  "approval_id": "VOUCHER_CREATE",
  "message": "다음 내용으로 전표 Draft를 등록하시겠습니까?",
  "policy": {
    "required": true,
    "ttl_seconds": 1800
  }
}
```

`approval_id`는 Source/IR의 **정적 Approval ID**다.

실제 실행에서 생성되는 `ApprovalRequestId`와 동일하지 않다.

Approval은 Source/UI 구현이 아니라 Skill의 static control semantics 일부이므로 IR Node로 존재하지만, 다음은 IR 밖에 유지한다.

```text
Approval Routing
Approval UI
Approval Persistence
Human/Role selection
Resume Job Scheduling
ApprovalRequestId instance
```

---

# 6. WriteExpression Node

```json
{
  "kind": "write",
  "node_id": "write0001",
  "tool_ref": "tool0003",
  "approval_ref": "VOUCHER_CREATE",
  "arguments": [
    {
      "name": "account_code",
      "value": {"kind": "symbol_ref", "symbol_id": "s0010"}
    },
    {
      "name": "amount",
      "value": {"kind": "symbol_ref", "symbol_id": "s0012"}
    }
  ],
  "type": {
    "kind": "named",
    "name": "VoucherDraft"
  }
}
```

`WriteExpression`은 정적인 WRITE semantics와 argument graph만 표현한다.

다음은 Runtime에서 생성/계산하므로 IR에 저장하지 않는다.

```text
BusinessOperationId
IdempotencyKey
PayloadHash
write_intent_hash
ApprovalRequestId
CommitState
Verification result
```

---

# 7. WRITE는 Expression

WRITE Result를 `let`으로 바인딩할 수 있다.

```text
LET
 ├─ target = s0020
 └─ value
      WRITE
       ├─ tool_ref
       ├─ approval_ref
       └─ args
```

v0.2에서는 standalone unbound WRITE보다 Result Binding을 권장한다.

Write Result의 Commit/Verification runtime state는 static IR에 포함하지 않으며, 실제 Runtime `WriteExecutionOutcome` / `WriteResultEnvelope`에서 관리한다.

---

# 8. Approval / Write Link

IR Validator는 `NSL-0.2-STRICT`에서 다음을 보장한다.

```text
approval_ref points to unique approval_id
approval node occurs before write
each WRITE references exactly one Approval
each Approval is linked to exactly one WRITE
unused Approval is rejected
one WRITE maximum under strict profile
write not nested under foreach
```

즉 Approval↔WRITE 관계는 **exactly 1:1**이다.

이 관계는 static semantic link이며, 실행 중 생성되는 `ApprovalRequestId`와는 별개다.

---

# 9. CHECK Data Policy

기존 Strict 정책 유지:

```json
{
  "require_complete": true,
  "on_partial": "UNKNOWN",
  "on_unknown": "UNKNOWN"
}
```

Runtime의 `PreWriteEligibility` 계산에서 UNKNOWN은 BLOCKED로 처리한다.

```text
CHECK UNKNOWN
→ no approval-to-write transition
→ no WRITE
```

단, `PreWriteEligibility`, `CommitState`, `ExecutionStatus`는 서로 다른 runtime lifecycle layer이며 IR에서 하나의 status로 합치지 않는다.

---

# 10. Static Analysis v0.2

```json
{
  "analysis": {
    "resource_bounds": {
      "max_tool_calls": 8,
      "max_loop_iterations": 20,
      "max_emitted_rows": 10,
      "bounded": true
    },
    "write_analysis": {
      "write_node_count": 1,
      "approval_node_count": 1,
      "approval_write_mapping_count": 1,
      "unused_approval_count": 0,
      "max_write_calls": 1,
      "writes_inside_loop": false,
      "all_writes_approved": true,
      "exact_approval_write_mapping": true,
      "requires_verified_package_for_write": true
    },
    "safety": {
      "dynamic_tool_reference": false,
      "arbitrary_io": false,
      "unsupported_write_operation": false
    }
  }
}
```

`requires_verified_package_for_write`는 IR 자체에 embedded signature가 있다는 의미가 아니다.

의미:

```text
WRITE-bearing Skill
→ Production execution requires Verified Signed NSP Trust Evidence
```

`max_write_calls=1`과 `writes_inside_loop=false`는 일반 Compiler Option으로 완화 가능한 knob가 아니라 Strict SemanticsProfile의 static safety result다.

---

# 11. Hash Model

IR / Compiler와 NSP Package Layer의 hash ownership을 분리한다.

Compiler / IR이 소유하는 canonical semantic hashes:

```text
source_bundle_sha256
semantic_sha256
```

권장:

```json
{
  "hashes": {
    "source_bundle_sha256": "...",
    "semantic_sha256": "..."
  }
}
```

`semantic_sha256`은 Runtime execution 의미를 결정하는 canonical semantic payload에 기반하며 build/debug metadata는 제외한다.

Package/artifact integrity hash는 NSP Package Layer가 소유한다.

```text
Compiler / IR
  source_bundle_sha256
  semantic_sha256

NSP Package
  package/artifact integrity hash
  publisher signature
  trusted key metadata
```

IR에 package `artifact_sha256`을 별도 canonical semantic field로 추가하여 semantic hash ownership과 package integrity ownership을 혼합하지 않는다.

---

# 12. Package Trust Metadata Boundary

IR 1.1의 canonical semantic schema에는 별도의 **embedded SignatureMetadata를 필수로 추가하지 않는다.**

Production WRITE trust는 기존 Signed NSP Package에서 제공한다.

```text
Canonical NSO / SemanticHash
        ↓
NSP Build
        ↓
Package Integrity Hash
        ↓
Publisher Signature
        ↓
Trusted Key Verification
        ↓
Verified Package / Verified Skill Artifact
```

따라서 다음과 같은 runtime/package trust data는 static semantic IR에 넣지 않는다.

```text
signature bytes
publisher key id
certificate / key chain
package signature algorithm metadata
verified trust decision
```

필요한 package signature metadata는 `.nsp` package manifest/security metadata에 존재한다.

---

# 13. NSP Package Signing Boundary

Production signing 대상은 IR 자체의 별도 signature field가 아니라 **NSP Package에서 정의한 canonical package/artifact payload**다.

원칙:

```text
Semantic change
→ semantic_sha256 changes
→ rebuilt package integrity changes
→ existing package signature no longer validates the rebuilt package
```

Compiler는 canonical NSO와 SemanticHash를 생성하고, Production signing은 NSP Build/Signing Layer가 담당한다.

즉:

```text
Compiler Core
!→ package signing
!→ NsoArtifactSigner
```

를 유지한다.

---

# 14. Build Metadata

기존 Include Source Manifest를 유지한다.

```json
{
  "build": {
    "compiler_version": "0.2.x",
    "sources": [
      {"logical_path": "skills/voucher.ns", "sha256": "..."},
      {"logical_path": "common/finance.ns", "sha256": "..."}
    ]
  }
}
```

Build Metadata는 semantic execution contract와 구분하며 `semantic_sha256` 계산 대상에서 제외한다.

SourceBundleHash와 SemanticHash의 v0.1 canonicalization 규칙은 변경하지 않는다.

---

# 15. Runtime Load Validation

IR 1.1 Loader/Validator:

```text
format == "NSO"
IR/language version compatibility
known features
symbol/node integrity
tool refs
type validity
bounded loop
check policy
approval refs
approval↔write exact 1:1
unused approval absent
write count
write loop nesting
write tool capability
static analysis shape
hash integrity
```

Production package trust는 Runtime Load/Structural Validation과 분리한다.

```text
IR Loader/Validator
→ canonical IR / hash / structure

Runtime Preflight
→ Verified Signed NSP Trust Evidence
→ Tool Contract fingerprint
→ runtime feature support
```

Runtime instance 값인 BusinessOperationId/ApprovalRequestId/IdempotencyKey/PayloadHash는 IR Load Validation 대상이 아니다.

---

# 16. Version Compatibility

Runtime v0.2:

```text
IR 1.0 → supported
IR 1.1 → supported
```

Compiler mapping:

```text
NSL 0.1 Source → IR 1.0
NSL 0.2 Source → IR 1.1
```

NSL 0.2 Source가 WRITE를 사용하지 않더라도 IR 1.1을 생성한다.

Runtime v0.1:

```text
IR 1.1 Skill → unsupported/reject
```

v0.1 Source를 v0.2 Compiler로 다시 Compile할 때는 기존 deterministic Node ID, canonical IR 1.0 shape, SemanticHash를 변경하지 않는 regression gate를 유지한다.

---

# 17. Canonical Serialization

기존 규칙 유지:

```text
UTF-8
stable keys
stable arrays
Decimal as string
Money as structured value
deterministic IDs
```

v0.2의 additive APPROVAL/WRITE node가 없는 IR 1.0 artifact에서는 기존 canonical bytes가 변해서는 안 된다.

Canonical serialization은 다음을 위한 Single Source다.

```text
SemanticHash
IR round-trip
Replay artifact identity
Regression comparison
```

Package signing은 이 canonical semantic artifact를 포함하는 NSP Package Layer에서 수행한다.

---

# 18. Python Object Model

공유 IR 객체:

```text
ApprovalStatement
WriteExpression
ApprovalPolicy
```

모두 `nsl.ir`의 Single Source of Truth에 단 한 번 정의한다.

다음은 IR Object Model에 추가하지 않는다.

```text
SignatureMetadata
BusinessOperationId runtime value
ApprovalRequestId
IdempotencyKey runtime value
PayloadHash runtime value
PolicyDecision
CommitState execution value
VerificationResult execution value
```

Shared type 자체가 필요하면 `core/`에 둘 수 있으나, runtime value를 `SkillObject` 또는 static IR node에 직렬화하지 않는다.

---

# 19. Sample Body

```json
[
  {
    "kind": "check",
    "node_id": "check0001",
    "check_id": "ACCOUNT_VALID"
  },
  {
    "kind": "approval",
    "node_id": "approval0001",
    "approval_id": "VOUCHER_CREATE",
    "message": "전표를 등록하시겠습니까?"
  },
  {
    "kind": "let",
    "node_id": "stmt0010",
    "target_symbol_id": "s0020",
    "value": {
      "kind": "write",
      "node_id": "write0001",
      "tool_ref": "tool0003",
      "approval_ref": "VOUCHER_CREATE",
      "arguments": []
    }
  }
]
```

이 Body는 static skill semantics만 표현한다.

실행 시의 `BusinessOperationId`, ApprovalRequestId, PayloadHash, IdempotencyKey, Commit/Verification outcome은 Runtime state/tool request에서 별도로 생성·보존한다.

---

# 20. IR Safety Invariants

```text
IRW-01 write requires WRITE tool
IRW-02 write has approval_ref
IRW-03 approval_ref points to a unique Approval
IRW-04 Approval↔WRITE mapping is exactly 1:1 under NSL-0.2-STRICT
IRW-05 unused Approval is rejected
IRW-06 write count <= 1 under strict
IRW-07 write not in foreach
IRW-08 WRITE-bearing skill requires verified Signed NSP trust at Production runtime
IRW-09 no binding/endpoint credentials
IRW-10 all types resolved
IRW-11 format remains "NSO"
IRW-12 runtime identities are not serialized into static IR
IRW-13 v0.1 deterministic Node IDs / canonical IR / SemanticHash remain unchanged
```

`IRW-08`은 embedded IR signature requirement가 아니라 Runtime Preflight trust requirement를 뜻한다.

---

# 20.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-003  BusinessOperationId를 static IR runtime value와 분리
CHG-004  IdempotencyKey / PayloadHash를 runtime invocation data로 분리
CHG-010  Signed NSP Trust Boundary 재사용
CHG-011  Approval↔WRITE exactly 1:1
CHG-014  Language Version → IR Version deterministic mapping
CHG-015  v0.1 deterministic Node ID / canonical IR / SemanticHash 보존
CHG-016  format="NSO" 및 additive IR compatibility 유지
CHG-031  SemanticHash / Package Integrity ownership 분리
```

본 문서는 위 Closure 결정을 NSO IR 1.1 Schema에 반영하며, static Skill Semantics와 runtime execution instance state의 경계를 고정한다.

---

# 21. 최종 정의

> **IR 1.1은 v0.1 Typed Deterministic IR을 additive하게 확장하여 Approval/Controlled Write의 static execution contract를 표현한다. Runtime business identity, Idempotency/Payload identity, Commit/Verification state, Approval workflow, external Binding/DB transaction, Package signing implementation은 IR 밖에 유지한다.**
