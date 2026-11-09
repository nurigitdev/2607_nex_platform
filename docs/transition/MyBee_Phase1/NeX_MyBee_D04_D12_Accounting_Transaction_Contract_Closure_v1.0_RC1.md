# NeX–MyBee D04/D12 Accounting Transaction Contract Closure v1.0-RC1

**작성 기준일:** 2026-11-09 (Asia/Seoul)  
**범위:** D04 회계업무 + D12 프로젝트수행업무 / 연계: D08 급여, D15 구매, 공용비용 배부  
**성격:** **6개 핵심 계약의 설계 결정 폐쇄(Decision Closure)** 및 구현 전 검증 기준. 구현·회귀 테스트 완료 문서가 아님.  
**상태:** **CONDITIONAL CLOSURE — 계약 결정 C1~C6 수립, 원본 PDF 본문 대조 및 실 DB/코드 Acceptance 미완료**  
**절대 불변 기준:** **NeX Platform v2.1 Frozen Architecture + NeX Agent v2.1 + NSL v0.2**  
**MyBee 위치:** NeX 기반 사무업무 AX Service. MyBee가 NeX 플랫폼 공통 기능·원장 소유권·승인 권한을 대체할 수 없음.

> **출처 확인의 한계:** 2026-11-09 GitHub `main` 저장소에서 새 `D04 v1.9.pdf`(7,570,040 bytes)와 `D12 v2.8.pdf`(7,118,923 bytes)의 존재와 Git Blob SHA를 확인했다. 그러나 현재 연결된 GitHub 파일 조회는 대용량 PDF/DOCX를 텍스트로 반환하지 않아 **PDF 본문을 직접 읽거나 페이지 단위로 검증하지 못했다**. 아래 MyBee 업무코드·업무 흐름은 조회 가능한 관련 HTML 설계서로 교차 확인한 사실이고, PDF 직접 대조는 **서명 전 Gate**로 남긴다. 추정 내용을 원문 확인 결과인 것처럼 표시하지 않는다.

---

## 0. 최종 판단: 무엇을 닫고, 무엇을 아직 닫지 않는가

| 구분 | 결정 | 결과 | 해제 조건 |
|---|---|---|---|
| C1 기안/품의 최종 결재 증명 | EOS 기존 `BUSINESS_FORMAL` Approval Proof를 재사용하며, 전표 생성 전 반드시 검증 | **설계 결정 수립** | D04/D12 PDF의 상세 요구와 필드 대조, 기존 EOS 커맨드 호환성 테스트 |
| C2 전표 상태 전이 | 업무결재, 회계승인, 원장기표를 별개 권한·사건으로 구분 | **설계 결정 수립** | 신규 회계 Aggregate/상태 API 스키마 검증 |
| C3 계정과목 유효성 | MyBee 채택 K-IFRS 기반 계정 Master 초기 이관, `FL0004011` 통제 확장 | **설계 결정 수립** | 실제 계정표 seed/코드체계 원본 확정 |
| C4 회계 승인 권한 | 별도 회계 담당자 Human Gate, OA 최신 인가와 maker-checker 통제 | **설계 결정 수립** | OA 직책·법인·회계조직/역할 결합 정책 Acceptance |
| C5 GL Posting 원자성 | EOS 단일 PostgreSQL Tx에서 회계승인 기록+확정전표+분개+원장+Outbox Commit | **설계 결정 수립** | PostgreSQL 동시성/장애/unknown-commit 테스트 |
| C6 Project Allocation·대사 | POSTED 원장 단일 금액 사실 + 배부원장 + 재구축 가능한 손익 Projection | **설계 결정 수립** | 급여/구매 원천 매핑 및 월별/부분배부 대사 테스트 |
| NeX Frozen 변경 | 직접 수정하지 않음. 기존 계약과 충돌하면 **Controlled Amendment Candidate**로 별도 격리 | **확정 불변** | 기존 v2.1 Authority Hierarchy 준수 |

**이 문서의 의미:** 지금 단계에서 필요한 **업무/기술 계약의 내용은 정의**한다. 그러나 위 미완료 Gate를 통과하지 않고 `FROZEN / IMPLEMENTATION ACCEPTED`로 표기하지 않는다.

## 1. Authority / Ownership Invariants

### 1.1 NeX v2.1 책임 배치

| 주체 | 소유하는 정본/책임 | 소유하지 않는 것 |
|---|---|---|
| NeX-AE / IA / PA | 사용자의 의도·에이전트 실행·NSL Skill 진입 및 Project 실행 | 회계 승인자 권한, GL 직접 쓰기 |
| NeX-WC | WorkItem, 조정, **Human Approval Workflow**, 승인 WorkItem·결정 전달 | 회계 원장, 회계금액 정본 |
| NeX-OA | Principal, Tenant/Org/Project RoleBinding, 최신 Authorization·위임 검증 | 회계 업무 승인 결정 자체 |
| NeX-AG | Trust/Policy Governance, Kill-switch | 금액 정본, 전표 기표 |
| NSL v0.2 | 결정적 Skill 실행·단일 Controlled WRITE·승인·Idempotency/Commit/Verification 경계 | 다단계 Workflow Orchestration, 직접 SQL/외부 시스템 접근 |
| **NeX Enterprise OS (EOS)** | Project Master/회계 원장, Account Master, Business Formal Approval Proof, GL, Allocation, 예산 금액 정본 및 Canonical Business API | WC 조정 엔진, OA 인가 정책의 최종 Authority 대체 |
| NeX-WA | 업무 산출물·증적/기록 연계 | 회계 원장, 승인권한, 스케줄러 |
| **MyBee AX Service** | D04/D12/D08/D15 업무코드·업무규칙·도메인 실행 정책/UX | 독립 Agent Runtime, 독립 GL 정본, NeX 승인 엔진 복제 |

**A-01** MyBee의 `mbacct.*`, `mbproj.*`, `mbhr.*`, `mbpur.*`는 **도메인 논리 데이터 모델 참조**이며 NeX에서 물리 DB를 동형 복제해야 한다는 뜻이 아니다.  
**A-02** `EOS Business Approval SoR + WC Workflow + OA PDP`의 Frozen Hybrid 승인 경계를 유지한다.  
**A-03** 기존 승인 도메인 `BUSINESS_FORMAL / AGENT_FORMAL / NSL_WRITE`의 의미를 변경하지 않는다. 회계 승인 필요성을 이유로 WC/NSL에 새 승인 도메인을 임의 추가하지 않는다. 회계 승인 목적은 **EOS 회계 업무·OA 권한·별도 Approval Instance**로 구분한다.  
**A-04** 서비스 DB 간 FK/Join·전역 SQL 트랜잭션을 요구하지 않는다. 서비스 간에는 계약된 Reference, Outbox/Inbox, Idempotency, Status Reconciliation을 사용한다.

### 1.2 절대로 혼동하면 안 되는 세 가지 승인/실행

1. **Business Approval:** 기안/품의의 예산·거래·행위 자체를 승인. 기존 EOS `eos_approval_proof`의 정본 및 WC Human Workflow 활용.
2. **NSL WRITE Approval:** NeX NSL Skill의 통제된 WRITE 실행을 승인하는 실행 경계. Business Approval을 대신하지 않으며 그 역도 성립하지 않는다.
3. **Accounting Approval:** **전표 내용·계정과목·증빙·차대·회계기간**에 대한 회계 승인 담당자의 별도 Human Decision. 이 결정을 확인한 후에만 GL Posting.

`BUSINESS_APPROVED != NSL_WRITE_APPROVED != ACCOUNTING_APPROVED != POSTED`.

**주체가 같은 사람이어도 각 결정은 별도 Object/Proof/Scope로 기록한다.** 단, 원칙적으로 기안자와 전표 회계승인자는 분리한다. 현재 EOS 승인 Instance의 `requester_ref_type`은 `oa.user`로 제한되어 있으므로, **PA가 사람을 대신해 기안하는 Phase-1 경로는 인간 OA 요청자와 대리 수행 Agent/Delegation Evidence를 별도로 결합**해야 한다. 무인 Agent가 임의의 사람 ID를 위조해 기안하는 방식은 금지한다.

---

## 2. C1 — Approved Business Document Proof Contract

### 2.1 Contract ID / SoR / Trigger

- **ID:** `EOS.BUSINESS_DOCUMENT.APPROVAL_BINDING.v1` (추가 제안 계약명; 아직 구현된 API 이름이 아님)
- **SoR:** EOS `BUSINESS_FORMAL` Approval Instance/Proof + EOS 업무문서 스냅샷·바인딩 레코드
- **Workflow:** WC 승인 WorkItem·Human Decision
- **Authorization:** OA 최신 Policy Decision / Tenant & Organization Scope
- **Trigger:** 최종 결재 후 `APPROVED`와 불변 Proof 발급. **이후** 회계 전표 제안 생성 허용.

### 2.2 기존 구현에서 반드시 재사용할 필드

`eos_approval_proof`에는 이미 다음이 있다: `tenant_id`, `approval_proof_id`, `approval_instance_id`, `business_operation_id`, `final_approval_stage_id`, `final_wc_decision_id`, `approval_domain`, `protected_operation_ref`, `payload_hash`, `write_intent_hash`, `policy_hash`, `instance_binding_hash`, `decision_chain_hash`, `final_decision_hash`, `proof_version`, `proof_hash`, `issued_at`.

**Decision C1-1:** 이 Proof를 다른 형태의 자체 서명 토큰으로 교체하지 않는다. MyBee는 기존 EOS Proof ID와 승인된 문서 Snapshot을 참조한다.

### 2.3 추가적인 승인문서-전표 바인딩(신규 EOS 확장 후보)

```json
{
  "schema_version": "eos_business_document_voucher_binding.v1",
  "tenant_id": "TENANT_1",
  "document_ref": {"type": "eos.business_document", "id": "DOC_ID"},
  "document_revision": 3,
  "document_type": "PURCHASE_APPROVAL",
  "approved_payload_hash": "sha256:<64 hex>",
  "approved_attachment_manifest_hash": "sha256:<64 hex>",
  "business_approval_proof_ref": {
    "type": "eos.approval_proof", "id": "APPROVAL_PROOF_ID"
  },
  "approval_purpose": "BUSINESS_EXPENDITURE",
  "approved_envelope_ref": "IMMUTABLE_APPROVED_ENVELOPE_ID",
  "source_business_operation_id": "BUSINESS_OPERATION_UUID",
  "effective_until": null
}
```

*위 예시는 스키마가 아니며 `sha256:<64 hex>` 등의 표시는 구조 설명용 placeholder다.*

`approved_envelope`에는 최소 `tenant/company`, 문서 개정차수, 프로젝트/공유비용 범위, 업무코드, 거래대상/거래유형, 승인 금액/통화/상한, 기간/유효성, 승인된 증빙 Manifest 및 변경 허용 범위를 고정한다. 계정과목이나 회계기간이 사후 확정되는 경우에도 원 승인 범위에서 허용된 **결정적 파생**임을 검증해야 한다. 금액·수취인·사용목적 등 승인 범위를 넓히는 변경은 신규 기안·재결재한다.

### 2.4 Validation / Consumption

- `approval_domain == BUSINESS_FORMAL`, `instance.state == APPROVED`, `approval_proof_id`가 동일 `tenant_id`의 정본에 존재해야 한다.
- `protected_operation_ref`, `payload_hash`, `proof_hash`, `document_revision`, 첨부증빙 Snapshot이 불변 승인본과 일치해야 한다.
- OA 최신 접근 권한과 문서의 유효범위를 전표 제안/Posting에서 재검증한다. 이미 확정된 합법적인 결재 증거 자체는 추후 담당자 조직변경만으로 임의 폐기하지 않되, 취소·중지·회수 등 명시적인 상위 상태는 fail-closed 처리한다.
- **하나의 기안/품의서가 여러 전표를 합법적으로 파생 가능**하다. 1:1 제약 금지. 대신 `approval_authorization_usage` 같은 **소진·한도 정본**을 EOS에서 트랜잭션으로 유지해 합계가 승인 금액/수량/기간을 초과하지 않도록 한다. 반복 지급/부분 검수/분할매입·분할 급여를 고려.
- 단순히 `business_approval_proof_ref`가 **존재한다는 사실**만으로는 충분하지 않다. **문서 Snapshot·승인 금액·전표의 경제적 내용**이 검증되어야 한다.
- 업무 결재 `REJECTED/RETURNED/CANCELLED/INVALIDATED`에서는 신규 전표 생성 불가. 재기안 시 문서 revision+proof가 새로 발급되어야 한다.

### 2.5 기존 코드와의 호환성 결함

현행 `eos_create_voucher_draft_command.v1`에서는 `business_approval_proof_ref`가 **선택 필드**이고, `eos_voucher_draft` 원천 `source_ref`가 NSL Approval Request를 가리키는 Golden A 경로가 있다. 이번 요구에 맞춰 다음 중 하나를 **새 버전의 승인된 Command**로 추가한다.

- **권고:** `eos_create_voucher_draft_command.v2`에서 사업결재 바인딩 **필수**, proof/문서 범위를 EOS에서 검증하고 기존 v1은 보존하되 MyBee Phase-1 신규 경로에서는 차단.
- v1를 변경해야만 한다면 Golden A/P8 회귀와 Frozen Compatibility를 통과한 Controlled Change만 허용.
- 감사/검증에서 사용해야 하므로 `business_document_ref`, `revision`, `business_approval_proof_id`, `approval_envelope_hash`는 정본의 영구 참조로 보존.

---

## 3. C2 — Voucher State Machine Contract

### 3.1 세 개의 Aggregate를 별도 관리

| Aggregate | 주 상태 | 책임 |
|---|---|---|
| `BusinessDocument` | `DRAFT → SUBMITTED → IN_APPROVAL → APPROVED` / `RETURNED`, `REJECTED`, `CANCELLED` | 업무 결재. 승인된 버전 변경 불가 |
| `VoucherCandidate` | `DRAFT → READY_FOR_REVIEW → RETURNED_FOR_CORRECTION` 또는 `POSTED`/`CANCELLED` | 업무승인 Proof를 가진 회계 검토 대상 |
| `Journal` | **`POSTED` 불변**, 정정은 별도 `REVERSAL/ADJUSTMENT` 회계전표 | GL의 실제 금액 정본 |

**Decision C2-1:** 회계승인은 `VoucherCandidate`에 대한 별도 인간 Decision/Proof 사건이며 EOS Posting에서는 이 증거를 수용하는 `AccountingApprovalAcceptance`를 남긴다. `APPROVED`는 기안 승인 또는 NSL WRITE 승인과 같은 상태로 취급하지 않는다.  
**Decision C2-2:** **Phase-1은 사람의 회계 최종승인 Proof를 EOS에서 수용(Acceptance)하는 단계와 GL Posting을 하나의 EOS 로컬 트랜잭션으로 처리**한다. WC에 기록된 최종 인간 결정 및 그에 따른 EOS `BUSINESS_FORMAL` Proof는 별도 선행 트랜잭션으로 이미 존재할 수 있다. 따라서 **WC 승인과 EOS Posting을 물리적으로 하나의 ACID Commit이라고 주장하지 않는다.** EOS는 `ACCOUNTING_APPROVED` 증거를 검증해 동일 Transaction에서 `PostingAcceptance + Journal + POSTED + Outbox`를 확정한다.  
**Decision C2-3:** WC의 회계 승인 결정은 먼저 확정됐지만 EOS Posting이 아직 반영되지 않은 **서비스 간 전달 지연**은 발생할 수 있다. 이를 사용자에게 `POSTING_SYNC_PENDING`(파생 상태)으로 명시하고 같은 BusinessOperationId로 대사한다. Phase-1에서 EOS 전표 정본에 별도 영속 `APPROVED_PENDING_POST` 상태를 두는 것은 권고하지 않는다. 영속 비동기 Posting을 도입할 경우 별도 SRS/ADR에서 승인 snapshot·재시도·대사를 명시한다.

### 3.2 허용 명령 및 전이표

| Command (신규 후보) | 입력 상태 | 주체 / 필수 조건 | 성공 출력 | 실패 |
|---|---|---|---|---|
| `FINANCE.VOUCHER_DRAFT.CREATE_APPROVED` | 아직 없음 | 승인된 기안 문서 Proof, 승인 Envelope 일치, NSL WRITE 허용 | `DRAFT` | Proof 불일치·없는 승인 차단 |
| `FINANCE.VOUCHER.SUBMIT_FOR_REVIEW` | `DRAFT/RETURNED_FOR_CORRECTION` | 기안자/회계담당자·검증 규칙, 차대 일치 | `READY_FOR_REVIEW` | 필수증빙/계정/기간 거부 |
| `FINANCE.VOUCHER.RETURN` | `READY_FOR_REVIEW` | 회계 검토 권한, 사유 필수 | `RETURNED_FOR_CORRECTION` | 다른 상태·미인가 차단 |
| `FINANCE.VOUCHER.APPROVE_AND_POST` | `READY_FOR_REVIEW` | **회계 승인 권한자 Human Decision**, EOS Posting All Gates | `Journal.POSTED`, `Voucher.POSTED` | 원자적 Rollback / 상태 유지 |
| `FINANCE.VOUCHER.CANCEL_DRAFT` | `DRAFT/RETURNED_FOR_CORRECTION` | 권한, 사유 | `CANCELLED` | POSTED 취소 금지 |
| `FINANCE.VOUCHER.REVERSE_APPROVED` | `Journal.POSTED` | 별도 정정 기안 승인·회계 승인 | **새 Reverse Journal** + 원본 연결 | 원본 수정 금지 |

회계 검토에서 수정이 필요하면 같은 `DRAFT`를 덮어쓰기하지 않고 **새 Revision 및 승인 전표 본문 hash**를 유지한다. 본문이 바뀌면 이전의 회계 검토·승인 시도는 무효화된다. 권한·기간·계정과목 검증은 **전표 생성 시 및 Posting 시** 수행한다.

### 3.3 필수 상태 불변조건

- **V-01** `POSTED`에는 반드시 1개 이상의 `journal_line`, 회계 승인 Decision, 승인 문서 Proof, Posting `business_operation_id`가 존재한다.
- **V-02** 하나의 `(tenant, voucher_candidate_id, revision)`은 **최대 1회의 GL Posting**만 허용한다.
- **V-03** `POSTED` 전표/분개 값의 `UPDATE/DELETE`를 API와 저장소 레벨에서 차단한다. 취소·정정은 새로운 연결 전표.
- **V-04** 회계 상태는 EOS SoR; WC 상태는 승인 Workflow에만 속한다. WC 결재가 성공한 것만으로 POSTED가 되지 않는다.
- **V-05** 기존 EOS `eos_voucher_draft`의 DB Check `state = 'DRAFT'`는 변경하지 않는다. Posting을 위해 이 레거시/골든 경로의 상태를 `POSTED`로 강제로 바꾸지 말고 **신규 Posting Aggregate 또는 명시적 additive 확장** 사용.

---

## 4. C3 — K-IFRS Based Account Catalog / Posting Validity Contract

### 4.1 Baseline 기준

**사용자 결정:** MyBee 설계서에서 선택한 **K-IFRS 기반 계정과목표**를 초기 Account Master로 적용하고 신규 계정과목은 `FL0004011 계정과목 신설`을 통해 추가할 수 있도록 한다.  
**회계 표준과 코드표의 차이:** K-IFRS 회계기준과 회사별 **상세 계정코드표(chart of accounts)**는 동일한 것이 아니다. 따라서 “K-IFRS 기반”의 의미는 **MyBee가 채택한 실제 초기 계정코드·명칭·유형·상위과목·표시항목·계정 매핑**을 고정 버전으로 seed하고 회계기준의 인식·측정·표시 정책에 매핑한다는 뜻으로 사용한다. 임의의 보편 K-IFRS 계정코드 목록을 생성하지 않는다.

### 4.2 기존 EOS `eos_account`와 추가 필드

현재 EOS: `tenant_id`, `account_id`, `account_code`, `name`, `category(ASSET/LIABILITY/EQUITY/REVENUE/EXPENSE)`, `account_type`, `status(ACTIVE/INACTIVE)`, `effective_from/until`, `version`.

**신규 계약 후보:** `account_catalog_version`, `parent_account_ref`, `kifrs_mapping_ref`, `financial_statement_line_ref`, `postable`, `effective_period`, `allowed_business_codes`, `allowed_project_dimensions`, `account_nature`, `approval_policy_ref`, `created_from_work_code`(FL0004011 등), `approved_catalog_change_ref`.

추가 필드의 실제 정규화 구조(별도 `eos_account_catalog` / `eos_account_mapping` / `eos_account_policy`)는 Source Audit과 SRS 단계에서 선택한다. 기존 Account ID·Code는 변경하지 않는다.

### 4.3 Posting 필수 검사

- 계정이 전표 `tenant/company` 및 회계일 기준으로 존재·유효·활성 상태인지 확인하고 Posting 순간에도 동일한 룰·계정 기준의 유효성을 재검증.
- 최상위 집계계정에는 직접 Posting을 금지(`postable=true` leaf-level 정책).
- 차/대변 부호 및 분개 규칙은 Decimal로 판정; 총차변 = 총대변, 통화·회계기간·허용 보조차원 검증.
- `FL0004005` K-IFRS 인식 판정 → `FL0004006` 사규 적용 → `FL0004007` 분개 생성 → `FL0004008` 회계승인 → `FL0004009` 기표 순서를 업무 코드와 실행 증거로 추적.
- 회계기간이 `OPEN`인지 Posting Tx 내에서 lock 확인; `CLOSED`/`LOCKED` 상태면 실패. 뒤늦게 회계일을 바꾸어 과거 기간에 기록하지 않는다.
- 검토 시점에 계정/분개 Rule Version이 바뀌면 Posting 금지 후 재심의. 과거 POSTED 기준정보의 역사적 Snapshot은 변경하지 않음.
- `FL0004011`은 K-IFRS 기본 계정과목의 임의 수정이 아니라 **승인된 추가/후속 효력 발생**만 허용하며 OA 회계기준관리 권한과 승인 증거가 필요.
- Phase-1 첫 Posting Gate는 KRW를 우선 수용한다. 기타 통화가 이미 Draft로 지원되더라도 FX/통화별 차대·환율 인식 계약이 없는 신규 GL Posting은 차단하고 후속 버전에서 확대한다.

---

## 5. C4 — Accounting Approval & Separation of Duties

### 5.1 Authority 원칙

| 행위 | 권한 평가 | 누가 승인하는가 |
|---|---|---|
| 업무 기안 작성/상신 | OA `project/work_code` Scope | Project Member·PA 등 적법한 요청자 |
| 최종 기안 결재 | 기존 EOS `BUSINESS_FORMAL`+WC+OA 조직/금액 정책 | 승인 라인의 사람 |
| 회계 전표 제안·검토 준비 | `finance:voucher:prepare` (예시 정책 키) | 담당자 또는 승인된 Agent/NSL 실행 |
| **회계 전표 최종 승인** | **`finance:voucher:approve`** + tenant/company + 회계조직/회계담당 역할 + 최신 OA 권한 + SoD | **회계 승인 담당자(일반적으로 회계팀 팀장)** |
| GL Posting | `finance:voucher:post` 서비스 권한 + **사람 회계승인 Proof가 이미 유효** | EOS Deterministic Posting Service |
| 전표 역분개 | 별도 Business Approval + Accounting Approval | 회계 승인 담당자 |
| 배부 기준 개정 | `finance:allocation_policy:approve` | 정책 담당 승인자 |

**중요:** `finance:*`는 신규 제안 **업무 Scope 이름 예시**다. 현행 OA Scope에 즉시 존재한다고 가정하지 않으며 SRS에서 기존 Scope 및 인증 모델과 매핑/추가한다.

### 5.2 회계 승인 Proof 적용 방식

- 기존 `eos_approval_proof`의 `BUSINESS_FORMAL` 메커니즘을 **별도 회계 목적 Approval Instance**로 재사용할 수 있다. 단, `approval_purpose=ACCOUNTING_VOUCHER_POST`와 `protected_operation_ref=journal candidate + revision + content_hash`를 명확히 구분해야 한다.
- 기존 EOS 승인 정책의 `position_type=PART_LEAD/TEAM_LEAD/GROUP_LEAD/CEO/CHAIRMAN`만으로는 “회계팀 팀장”임을 보증할 수 없다. 따라서 OA에서 **회계조직·법인범위·회계 승인 역할을 교차검증**해야 하며, 단순 `TEAM_LEAD` 일치로 승인하지 않는다.
- 회계 승인 시 확인 대상: 정확한 전표 body hash, 첨부 Manifest, 승인 기안 Proof, 회계기간, 계정/분개 기준 버전, 금액·프로젝트 귀속, 중복 전표 여부.
- 동일 `principal`이 Voucher 작성자, 금액/증빙 변경자, 최종 회계승인자로 동시에 행동하는 것을 기본 차단. 예외는 별도 승인된 긴급정책/역할로만 통제하며 Phase-1 기본 정책에 예외 없음.
- 회계 승인 순간 권한/위임 Scope를 **최신** 값으로 다시 판정하고 OA Decision Evidence를 보존. 회계 승인 증거는 원장 Posting의 불변 참조로 남긴다.
- 결재자가 UI 버튼을 누른 것과 실제 EOS Transaction의 성공은 다르다. 브라우저 응답 실패 시 **BusinessOperationId로 EOS 조회 후 상태 확정**.

### 5.3 승인 중간 Race 정책

`APPROVAL_REVOKED`, 증빙/전표 revision 변경, 계정 비활성, period close, 회계담당 역할 해제, 금액 승인 한도 초과 등 하나라도 발생하면 해당 시점의 Posting 검증에서 **fail closed**. 이 경우 기존 최종 승인 결정의 원본은 감사에 남기되 새 수정본으로 Posting하지 않는다.

---

## 6. C5 — Atomic GL Posting Contract

### 6.1 Local Atomicity vs Business Transaction

- **Logical Business Transaction:** 기안 제출→업무 최종 결재→전표 작성→회계 승인→원장 기표→Project 배부/손익 조회까지의 **업무적 일관성**.
- **Physical PostgreSQL Transaction:** 각 SoR 서비스가 소유한 DB에서 원자적으로 처리할 수 있는 짧은 단위. 서로 다른 WC/OA/WA/EOS DB에 걸친 글로벌 ACID 트랜잭션을 주장하지 않는다.
- **Phase-1 EOS Posting Transaction:** `FINANCE.VOUCHER.APPROVE_AND_POST`는 **이미 완료된 사람 회계승인 게이트(별도 WC/EOS Proof)**의 정확한 Snapshot/권한 근거를 확인한 후 **하나의 EOS DB Commit**에서 회계승인 수용 기록+GL+Posting 결과+Outbox를 만든다. WC의 원래 결재 기록이 이 EOS Commit에 포함되는 것은 아니다.

### 6.2 권고 처리 순서 (EOS DB, 1 Unit of Work)

```text
BEGIN
  1. Lock VoucherCandidate(current revision) + AccountingPeriod
  2. Lock ApprovalEnvelope usage / idempotency identity if needed
  3. Read and verify EOS Business Formal Proof + frozen document binding
  4. Validate fresh, already-fetched OA decision evidence / delegated scope / SoD
     (No network call while the PostgreSQL transaction is open)
  5. Validate ACTIVE account, effective date, rule versions, currency, dimensions
  6. Validate SUM(debit) == SUM(credit), nonzero, account-level invariants
  7. Assert posting idempotency; lock existing result on duplicate
  8. INSERT immutable AccountingApprovalAcceptance (WC/EOS human proof & exact candidate hash)
  9. INSERT eos_journal_header + eos_journal_line (candidate proposal)
 10. INSERT ledger entry references; mark candidate POSTED by CAS(version/state)
 11. Commit approval envelope usage (amount/source-line consumed)
 12. INSERT eos_business_operation/eos_idempotency/outbox/audit result
COMMIT

On any exception before COMMIT => ROLLBACK all steps.
After ambiguous connection loss => Query idempotency key / business operation state;
                                    do NOT blind retry a new Posting.
```

**주의:** 기존 `EosBusinessTransactionCoordinator`가 동일 Unit of Work에서 BusinessOperation/Idempotency/Outbox를 함께 쓰는 토대를 제공한다. 신규 Posting은 그 재사용/확장이지 별도 트랜잭션 엔진을 만드는 것이 아니다. **OA 실시간 권한 조회·WC/WA 호출은 DB 트랜잭션을 열기 전에 수행**하며, DB 트랜잭션 안에서는 짧은 TTL의 검증된 Evidence·Snapshot·CAS/DB 제약만 검사한다(NeX DB Foundation의 외부 I/O 중 DB Tx 금지 원칙). OA 권한 철회와 EOS Commit 사이의 분산 TOCTOU는 영(0)으로 단정하지 않는다. 전파 지연·권한 버전 검증·고위험 작업 중지 정책 및 사후 감사/역분개를 별도 보완한다. 정확한 SQL/CAS/DB isolation 구현은 Source Audit 후 SRS에서 고정한다.

### 6.3 Minimal Canonical GL Tables (신규 EOS 확장 후보)

| Aggregate | 대표 필드 | 필수 제약 |
|---|---|---|
| `eos_accounting_period` | tenant, company, fiscal_year, period, status, version | CLOSED 차단, 선형 상태 전이, Posting 시 lock |
| `eos_journal_candidate` | tenant, candidate_id, revision, payload_hash, business_document_binding, state | 전표 내용 Snapshot, 이전 revision 불변 |
| `eos_accounting_approval_acceptance` | tenant, candidate_id/revision, WC/EOS approval_proof_ref, approver_ref, OA decision_ref, body_hash, accepted_at | 선행 인간 결정 Proof를 현재 Posting에 수용, SoD, append-only |
| `eos_journal_header` | tenant, company, journal_id, posting_date, currency, accounting_period, source_candidate_id, approval_proof, operation_id | `(tenant, source_candidate_id, revision)` 1회 Posting |
| `eos_journal_line` | tenant, journal_id, line_no, account_id, debit, credit, posting_dimensions, evidence_ref | 차대 검증, 행 불변, valid account |
| `eos_ledger_entry` / balance projection | tenant, journal_line_ref, account, amount, period | entry는 불변; 잔액은 재구축 가능 투영 |
| 기존 `eos_business_operation`,`eos_idempotency`,`eos_outbox` | operation_id, stable idempotency_key, payload_hash, result, event | exact replay은 동일 결과, 다른 payload는 409 |

**권고:** 원래의 회계 담당자 Decision은 WC Human Workflow/EOS Approval Proof에 별도로 저장될 수 있으나, **그 Decision을 특정 전표 Revision에 적용한 EOS `PostingAcceptance`와 journal records, candidate POSTED 상태는 반드시 같은 로컬 Commit**이다. WC 승인 후 EOS 전표가 아직 미확정인 구간은 숨기지 않고 `POSTING_SYNC_PENDING` Projection으로 노출하며 대사한다. 향후 영속 `APPROVED_PENDING_POST` 상태를 도입하려면 별도 Contract가 필요하다.

### 6.4 Idempotency / Retry / Failure Semantics

- Stable Key 예: `tenant + journal_candidate_id + candidate_revision + operation=APPROVE_AND_POST`(사업 의미 고정, random/time/retry count 금지).
- 같은 Key+같은 Payload Hash: 기 생성된 Journal ID/Posting 결과 **그대로 반환**. 같은 Key+다른 Hash: `409 IDEMPOTENCY_CONFLICT`.
- 중복 버튼/동시 승인/큐 재배달: `(tenant, candidate_id, revision)` unique + row-lock으로 **Exactly-once logical outcome**.
- 응답이 없을 때: `COMMITTED?`를 EOS 정본으로 조회. `UNKNOWN_COMMIT_STATE`는 새 전표 생성 사유가 아니고 **reconciliation 대상**이다.
- Account/Period 변경 경합: Posting Tx에서 유효 버전/잠금 비교 후 일치하지 않으면 `STALE_REVIEW` 재검토.
- GL Commit 후 Projection 장애: GL은 Rollback하지 않는다. Projection `STALE/PENDING` 표기, Outbox 재전달·재구축으로 복구.
- NSL 단일 Controlled WRITE의 `verification failed after commit`은 보상성 중복 Posting 금지. 이미 commit된 Journal을 상태 조회로 재검증.

### 6.5 필수 감사 연결

모든 POSTED journal에는 다음 역추적 체인을 제공해야 한다.

`Journal → CandidateRevision → AccountingDecision/OA Decision → BusinessApprovalProof → ApprovedDocumentRevision/AttachmentManifest → Project/WorkCode/SourceOperation → NSL WRITE Audit`.

---

## 7. C6 — Project Allocation Ledger / Reconciliation Contract

### 7.1 세 원장의 역할

| 계층 | 금액의 의미 | 정본 여부 |
|---|---|---|
| **GL Journal / Ledger** | 회사 차원의 인식·기표된 회계 사실 | **유일한 회계 금액 정본** |
| **Project Allocation Ledger** | 기표된 적격 원가·수익을 Project·업무코드에 귀속시킨 **관리 회계적 분할 사실** | 배부 기록의 정본, GL 금액의 복제 정본 아님 |
| **Project P&L Projection** | GL 직접귀속 + 배부 근거를 기반으로 재계산한 손익 조회 | 파생 Projection, 개별 금액의 독립 진실 아님 |

**Decision C6-1 — Phase-1 단일 전략:** **`MANAGEMENT_ALLOCATION`**을 우선 적용한다. 급여·공용구매·공용비용의 GL 총액을 유지하면서 `Project Allocation Ledger`에 별도 배부한다. GL에 프로젝트별 원가대체 분개를 동시에 기표하는 방법은 기본적으로 사용하지 않는다. 후속 원가대체 필요 시 `GL_COST_TRANSFER` 모드를 명시하고 같은 원천 Pool에서는 `MANAGEMENT_ALLOCATION`을 손익에 다시 더하지 않는다.

### 7.2 Allocation Source Pool / Plan / Line (신규 EOS 후보)

| 개체 | 대표 필드 | 정의 |
|---|---|---|
| `cost_source_pool` | `pool_id`, `tenant/company`, `source_journal_line_id`, `recognized_amount`, `eligible_amount`, `currency`, `source_kind`, `allocation_mode` | POSTED 원장 라인으로부터 배부 가능한 금액 상한을 구성. 자산·재고는 비용 인정 시점에만 원가 풀로 전환 |
| `cost_allocation_plan` | `plan_id`, `plan_version`, `cost_kind`, `basis_kind`, `basis_source_ref`, `snapshot_hash`, `effective_period`, `approval_ref`, `state` | 배부 방식·승인 정책·원천 기준의 버전 |
| `cost_allocation_line` | `allocation_line_id`, `source_pool_id`, `project_id`, `work_code`, `cost_target`, `basis_qty`, `basis_ratio`, `allocated_amount`, `currency`, `source_record_ref`, `rounding_adjustment` | Project별 최종 관리배부 라인. 개인정보 비노출 projection 별도 |
| `cost_allocation_batch` | `batch_id`, `period`, `source_pool_set_hash`, `allocation_rule_version`, `status`, `reconciled_at`, `operation_id` | 단일 배부 실행/검증·완결 상태 |
| `project_pnl_projection` | `project_id`, `period`, `posted_direct`, `posted_allocated`, `unallocated`, `pending_business`, `reconciliation_watermark` | 보고용 조회 모델, 언제든 재생성 가능 |

**관계 키:** `(tenant_id, source_journal_line_id, eligible_cost_component_id, allocation_plan_version)` 단위로 중복 배부 방지. **어느 한 원천 비용도 여러 Pool에서 중복 인정해서는 안 됨.** 비용 귀속은 가능한 경우 `work_code`까지 보존하되, 공용비용의 업무코드가 결정되지 않은 상태를 허용하더라도 Project/회사 잔여 소유자와 사유를 명시한다.

### 7.3 Amount Conservation / Rounding

**R1.** `eligible_posted_amount = sum(allocated_amount) + unallocated_amount`, 통화별·원천 Pool별로 만족.  
**R2.** `eligible_posted_amount <= recognized_eligible_GL_amount`. 비용 인식되지 않은 자재 입고·선급금·재고자산을 즉시 Project 비용으로 만들지 않는다.  
**R3.** 최종 검증된 배부 Batch의 `unallocated_amount`가 0이 아니라면 `PARTIAL_RECONCILED` 등 상태를 분명히 표시하고 P&L에 임의로 완전배부 수치로 가장하지 않는다. 상시 업무 Project/공통비 잔여 Pool로 귀속시키는 정책이 있을 수 있으며 이를 근거와 함께 기록한다.  
**R4.** Decimal 연산만 사용. 화폐 최소단위 기준 고정, 나머지 금액은 미리 정의된 **결정적 tie-break(예: fractional remainder 우선, project_id 오름차순)**로 배정. 같은 입력/Rule Version → 같은 결과.  
**R5.** `batch_id/version`과 `source_pool_id` 기준 idempotent. 동일 원천+동일 승인 Version의 재배부는 같은 결과; Rule 개정/실적 확정 시에는 기존 결과를 삭제하지 않고 `REVERSAL/ADJUSTMENT` ledger를 추가.  
**R6.** `GL_COST_TRANSFER`를 사용한 원천 Pool에는 관리배부액을 Project P&L에 중복 계상하지 않는 **exclusive source accounting mode** 적용.

### 7.4 기준값의 출처 및 승인

MyBee 2026-10-28 공용비용 설계에서 확인되는 원천 우선순위를 NeX의 deterministic allocation rule로 매핑한다.

`실제 수행 기록 → 승인된 계획·업무 BOM → 사람/설비/라이선스 매개 기준의 배부 연쇄 → 지정 비율(사유 필수)`.

원천 증거가 누락되거나 무효이면 임의 비율을 LLM이 생성할 수 없다. `fallback` 사용 시 원칙과 사유·승인 정책이 있어야 한다. 개정된 배부 기준이 이미 기표된 GL을 변경하지 않는다.

### 7.5 급여 업무 확장 (D08)

- **월급여 총액**은 그룹/회사 단위 GL로 기표한다. 프로젝트별 별도 계좌지급 또는 개인별 GL 노출을 강제하지 않는다.
- 계획 산정의 **등급별 Man-Day 기준단가**와 실제 인건비 원가(개인 정보 포함)는 다른 객체·권한·표시 정책으로 분리한다.
- `FL0008022`는 해당 월 급여 원가 Source Pool과 Project Work Evidence/투입비율을 사용해 배부하고, `FL0004052`는 기표된 GL에 근거해 예산 집행 Projection을 갱신한다.
- Project PA/PM은 개인별 급여·계산의 분자/분모·개인 실제 단가·소인원 구성값을 조회하지 못한다. 권한 없는 세분화 필터/시계열 차분으로 역산 가능한 경우도 차단해야 한다(금액 마스킹만으로 불충분).
- 연말 확정 원가(`FL0004053`)는 Phase-1 이후. 과거 POSTED/배부 원본을 수정하지 않고 **현재 승인된 조정월**에 차액으로 기록.
- MyBee 인건비 v1.7의 원칙: D04가 `mbacct.budget` 금액 정본 소유, D12 `mbproj.project_budget`은 배정 링크. NeX에서도 이를 유지.

### 7.6 구매 업무 확장 (D15)

- 여러 Project의 구매 근거 `N`개를 **하나의 발주/품의 결재**로 묶을 수 있다. 발주 Approval는 하나지만 각 구매/전표 라인에는 `project_id/cost_target/source_purchase_line`을 남긴다.
- `FL0015010` 발주 승인과 `FL0004008` 회계 전표 승인은 **별개**다. 입고·검수 후 `FL0015019` 매입 전표 제안 → 회계 승인 → Posting.
- 발주 수량 120개 중 Project A 40개, B 60개만 검수/소비되고 20개가 남으면 20개를 즉시 원가 배부하지 않는다. 원천 재고/자산 유지, 이후 소비·불용 시 기준 증거를 바탕으로 Project 귀속한다.
- MPS/MRP/BOM 상세 자동화는 Phase-1 필수 선행이 아닌 경우 수동 근거·승인된 간소 정책으로 대체 가능. 단 공용발주·검수·재고 인식/원가 귀속 간 사실 구분은 유지.
- 현재 EOS `eos_voucher_draft.project_id NOT NULL`은 회사/공용 비용 1건을 여러 Project로 귀속하는 구조에 맞지 않을 수 있다. **기존 필드를 삭제하거나 null로 임의 변경하지 말고**, 신규 `eos_journal_candidate`는 company-/shared-scope를 허용하거나 별도 정식 `shared source pool` 바인딩으로 확장한다. Golden A 기존 Project draft 경로는 보존.

### 7.7 P&L Query Semantics

`POSTED_DIRECT`, `POSTED_ALLOCATED`, `UNALLOCATED`, `APPROVED_NOT_POSTED`, `PLANNED_BUDGET`, `FORECAST`, `RECONCILIATION_PENDING`을 **서로 다른 열/상태**로 표시. 당기 손익은 POSTED GL과 검증 완료된 Allocation만 확정값으로 제공한다. `as_of`, `period`, `posting_watermark`, `allocation_watermark`, `reconciled_at`, `currency`, `scope`, `data_classification` 필수.

관리자는 회계 GL 합계와 프로젝트 배부 집계 사이의 차이(`unallocated`, 직접귀속 등)를 즉시 식별할 수 있어야 하며, PA/PM은 OA Scope와 급여 비밀유지 규칙에 따라 제한된 Projection만 본다.

---

## 8. Cross-Service Business Transaction — Reference Flow

```mermaid
sequenceDiagram
  autonumber
  actor Human as 기안자/결재권자
  participant IA as MyBee IA/PA
  participant WC as NeX-WC (Workflow)
  participant OA as NeX-OA (Auth)
  participant EOS as NeX-EOS (SoR)
  participant NSL as NSL v0.2
  participant GL as EOS PostgreSQL (GL)

  Human->>IA: 기안·품의 작성/상신
  IA->>EOS: Business Document snapshot + operation
  EOS->>WC: BUSINESS_FORMAL approval workflow
  WC->>OA: 각 결재자 최신 권한 확인
  OA-->>WC: ALLOW/DENY evidence
  Human->>WC: 최종 기안 결재
  WC->>EOS: Approved decision (outbox/inbox, idempotent)
  EOS->>EOS: Immutable BusinessApprovalProof 발행
  IA->>NSL: 분개 Draft 생성 Skill 요청
  NSL->>EOS: 승인본·증빙·전표 Candidate 생성 WRITE
  EOS->>EOS: Proof/Envelope/회계 기준 검증
  EOS->>WC: 전표 회계 검토/승인 요청 (별도 instance)
  WC->>OA: 회계담당자 Scope/SoD 검증
  OA-->>WC: 최신 회계승인 인가
  Human->>WC: 회계담당자 최종 승인
  WC->>EOS: Accounting decision + exact candidate hash (cross-service)
  Note over WC,EOS: 외부 Decision 전달 지연 중 POSTING_SYNC_PENDING 표시 가능
  EOS->>GL: Verify proof; accept approval and POST in local ACID Tx
  GL-->>EOS: POSTED + journal_id + outbox
  EOS-->>IA: Posting 결과 (idempotent)
  EOS->>EOS: Project Allocation batch & Reconciliation
  IA-->>Human: Project P&L (posted/reconciled 구분)
```

**구현상 주의:** 위의 `Human`은 기안 결재자와 회계 승인자의 **서로 다른 역할**을 묘사한다. 실제 회계 approval을 받는 단계에서는 EOS/WC Hybrid Approval이 새 `ApprovalInstance`/Decision을 사용하고, EOS Posting 로컬 트랜잭션에서 승인 증거와 전표 상태를 검증한다. WC/OA/EOS 여러 DB의 모든 화살표가 하나의 SQL 트랜잭션은 아니다. 각 교차 서비스 이벤트는 inbox/outbox·dedupe·reconciliation의 대상이다.

### 8.1 Ownership / Transaction Matrix

| 단계 | 소유 DB | Local ACID 범위 | 후속 처리 |
|---|---|---|---|
| 업무문서 및 최종 결재 Proof | EOS + WC 별도 정본 | EOS 승인 Instance/Decision/Proof, WC 결정/Outbox 각각 원자적 | event delivery & binding verify |
| 회계 전표 Candidate 생성 | EOS | candidate + proof binding + idempotency + outbox | 회계 검토 작업 시작 |
| 회계 검토 승인 | WC decision + EOS SoR | WC 결정은 WC tx, EOS는 결정 증명 수신 및 본문/hash 검증 | EOS `ApproveAndPost` 진입 |
| **GL Posting** | **EOS** | **approval acceptance + journal header/lines + status + outbox + idem + usage** | Projection consumer |
| Project Allocation | EOS | source pools + allocation lines + conservation check + batch outcome | P&L rebuild |
| Project P&L projection | EOS read model/API | `at-least-once` 이벤트 재처리 가능한 idempotent upsert | freshness 상태 제공 |

---

## 9. MyBee D04/D12 Business Code Boundary

### 9.1 D04 P0 필수

| 코드 | 업무명 | 이유 |
|---|---|---|
| `FL0004003` | 증빙 개인 업로드 | 최소 증빙 진입점 (WA Artifact 참조) |
| `FL0004005` | K-IFRS 인식 판정 | 회계 기준 gate |
| `FL0004006` | 사내 회계규정 적용 | 정책 버전 gate |
| `FL0004007` | 분개 생성 | 결정적 전표 본문 생성 |
| **`FL0004008`** | **전표 승인** | **회계 담당자 별도 Human Gate** |
| **`FL0004009`** | **전표 기표** | **EOS 원자적 GL Posting** |
| `FL0004010` | 전표 역분개 | immutable correction |
| `FL0004011` | 계정과목 신설 | K-IFRS 초기 카탈로그의 통제 확장 |
| `FL0004012` | 예산 편성 | D04 예산 금액 정본 |
| `FL0004014` | 예산 대비 실적 집계 | Project P&L에 연결 |
| `FL0004015` | 원가 배부 | 공용 자원/인건비 분할 |
| `FL0004046` | 회계 기간 개시 | Posting open-period gate |
| `FL0004048` | K-IFRS 판정 규칙 등재 | 기본 Master/Rule seed |
| `FL0004049` | 분개 규칙 확정 | Rule version seed |
| `FL0004050` | 배부 규칙 확정 | Allocation Rule seed |

`FL0004008`이 MyBee Intent Catalog에서 조건부로 분류되어 있더라도, **이번 MyBee Phase-1 회계전표의 최종 사람 회계승인 요구를 생략할 수 있는 의미로 해석하지 않는다.**

회계·결산 전 영역 전체를 구현하는 것은 Phase-1 범위 밖: 연결재무제표·XBRL·세무 신고·복잡한 외화 평가·완전 결산 등. `FL0004022/4023` 마감 전체 업무는 후속이지만 **Posting 시 회계기간 잠금 및 CLOSED 차단**은 Phase-1 필수 기술 기능이다.

### 9.2 D12 P0 필수

| 코드 | 업무명 | 이유 |
|---|---|---|
| `FL0012001` | 프로젝트 신청 | 프로젝트 기안/승인 전 단계 |
| `FL0012002` | 사전 검토 | 적격성 확인 |
| `FL0012003` | NVT위원회 심의 | 해당 조직/프로젝트 정책 적용 시 필수 (단순 내부 프로젝트는 정책 검토) |
| `FL0012004` | 프로젝트 개설 | Project Master 정본 |
| `FL0012005` | 업무 구성 확정 | 업무코드의 필수 집합 및 버전 lock |
| `FL0012006` | PM 지정 | PA/사람 책임자와 OA Scope |
| `FL0012007` | 참여자 배정 | Member/Agent + 등급/투입 범위 |
| `FL0012008` | 예산 배정 | D04 금액 원장에 대한 Project 링크, 직접 금액 갱신 아님 |
| `FL0012013` | 진행 보고 집계 | MyBee Project **관리 최소집합 5건** 중 필수 코드; 최소 진행 상태 조회 |
| `FL0012026` | 프로젝트 종결 | MyBee Project **관리 최소집합 5건** 중 필수 코드; 최종 원가·미기표·미배부 검증 |
| `FL0012044` | 인력투입계획 확정 | D08 원가배부 기준(급여 확장 시) |

**MyBee 프로젝트 관리 최소집합 5건은 `FL0012004 개설`, `FL0012005 업무 구성 확정`, `FL0012006 PM 지정`, `FL0012013 진행 보고 집계`, `FL0012026 프로젝트 종결`이며 프로젝트 생성 시 업무 구성에서 누락·제외할 수 없다(D19 업무코드 명세서 v1.2).** 해당 코드를 프로젝트에 할당하는 행위와 종결 업무가 실제로 실행되는 시점은 구분한다. 기술적 `Project.create / active gate`는 필요한 코드가 누락되면 전파 실행 금지. D12의 프로젝트 관여 코드는 EOS Project/PA/WC/WA로 나뉘지만 **Project 상태와 회계 예산 금액의 SoR은 EOS**다. NVT/모(母) 프로젝트와 3단계 계층은 기존 NeX-EOS Project 정책을 재사용한다.

---

## 10. Current NeX EOS Source Audit — Verified Facts vs. Implementation Gaps

| 항목 | 실제 확인된 기존 소스/계약 | 이번 Gap 및 처리 |
|---|---|---|
| Frozen Authority | `NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md`: WC Workflow + EOS Formal Approval Hybrid, EOS Business Transaction SoR | **유지**, MyBee 아키텍처 우선 금지 |
| Approval Proof | `2511_eos_approval_proof.sql`: immutable Proof / hash/decision chain | C1 재사용; 문서 revision/approved envelope binding 추가 |
| Approval Policy | `2509_eos_approval_policy.sql`: BUSINESS_FORMAL, stage position 집합, requester-excluded | 회계 승인 권한이 조직 직책만으로 판정되지 않도록 OA 회계역할+Scope 보강 |
| Business Operation | `2501_eos_business_transaction_core.sql` + `business_transactions.py`: idempotency/outbox 단일 로컬 Tx | C5 재사용; Posting success/unknown reconciliation 신설 |
| Account | `2505_eos_account.sql`: account code/category/status/effective/version | K-IFRS mapping hierarchy/catalog + postable/authorization 추가 |
| Voucher Draft | `2506_eos_voucher_draft.sql`: header `project_id NOT NULL`, state CHECK `DRAFT` | 기존 Golden A 유지; new journal candidate/posting aggregate 추가 |
| Voucher Draft Contract | `create_voucher_draft_command.v1.schema.json`: **`business_approval_proof_ref` optional**, NSL Evidence 필수 | MyBee v2 경로는 Business Proof 필수 + snapshot 검증 |
| GL Posting | 현재 조사한 `database/nex-eos/migrations` 및 OpenAPI에 확정 GL Posting Aggregate/API 명세 확인 못함 | C5 신규 구현 대상; Source Audit로 중복 현존 여부 추가 검증 |
| Project Allocation | 현재 조사한 EOS migrations/OpenAPI에서 관리배부 Ledger 확인 못함 | C6 신규 구현 대상 |
| NSL | `2608_nsl/README.md`: 단일 controlled WRITE, Approval, Commit/Verification, Audit | orchestration은 WC, ToolExecutionPort 경계 유지 |
| MyBee PDF | D04 v1.9/D12 v2.8 pdf가 GitHub tree에 실제 존재 | 바이너리 전문 접근 실패 — PDF 페이지 검증은 Release Gate 미완료 |

### 10.1 기존 NeX v2.1 소스에서 확인한 구체적 계약 차이

- `eos_account`는 K-IFRS 원본 계정표에 매핑할 Reference/계층 필드가 현재 핵심 스키마에 없음.
- `eos_voucher_draft_line`은 `signed_amount NUMERIC(20,2)`를 사용하고 Draft Repository가 `Σ signed_amount = 0`을 검사함. 신규 GL은 `debit/credit` 또는 동등한 단일 정규화 의미를 정하고 기존 Draft 변환 규칙을 명시해야 함.
- `eos_voucher_draft.state`는 오직 `DRAFT`로 제한. Draft에 `APPROVED/POSTED` 값을 추가하는 단순 변경은 권고하지 않음.
- Business Formal Approval Instance는 EOS가 정본, WC에서 인간 결재 수행/결정을 전달. 회계 승인 시 기존 계층/역할 필드만으로 회계팀 전용 승인자를 보장하지 못함.
- 기존 `eos_create_voucher_draft_command.v1`에 Proof ref는 있어도 optional이며 이를 `BUSINESS_FORMAL Approved Document`와 결합해 검증한다는 규칙이 계약 필수조건으로 표현되지 않음.
- 회사/공용 매입·급여의 원천 회계행위를 project_id 1개로 고정하면 공유 Pool의 원천과 프로젝트 소비 귀속이 혼동될 수 있음. 신규 `Journal Candidate`에 company scope와 Project Allocation을 분리해야 함.

---

## 11. Verification & Acceptance Test Matrix

**Acceptance Gate 규칙:** Core Negative Case 1개라도 실패하면 Contract Implementation Acceptance 불가. PostgreSQL의 실제 row locking, unique key, rollback 및 concurrency 동작을 **SQLite 모의 테스트만으로 PASS 선언하지 않는다.**

| ID | 유형 | 시나리오 | Expected |
|---|---|---|---|
| CT-01 | Positive | 승인된 기안/품의서 Revision + 유효 Proof → 전표 제안 | Draft 1개 |
| CT-02 | Negative | `business_approval_proof_ref` 누락 | DENY; MyBee v2 경로에서 Draft 없음 |
| CT-03 | Negative | 다른 tenant의 Proof 참조 | DENY; 데이터 무노출 |
| CT-04 | Negative | 승인 문서 금액/프로젝트/증빙 변경 후 동일 Proof 제출 | DENY, 신규 승인 필요 |
| CT-05 | Negative | 문서 RETURNED/REJECTED/CANCELLED 이후 Draft 요청 | DENY |
| CT-06 | Boundary | 승인 문서 1건에서 분할 전표 여러 건 | 누적 사용액 ≤ Approved Envelope; 중복 소비 없음 |
| CT-07 | Negative | 승인된 금액 초과를 병렬 전표에서 동시에 소진 | 한 거래만 성공, 초과 실패 |
| CT-08 | Positive | K-IFRS 매핑 및 ACTIVE leaf 계정으로 정상 분개 | Validated Candidate |
| CT-09 | Negative | 계정 미존재/INACTIVE/기간 밖/비Posting 계정 | Posting DENY |
| CT-10 | Negative | 전표 본문 승인 후 계정·Rule Version 변경 | STALE_REVIEW, 재검토 |
| CT-11 | Negative | 차대 불일치 / Decimal 불량 / 잘못된 통화 | Posting ROLLBACK |
| CT-12 | Negative | 회계기간 CLOSED/동시 마감 경합 | Posting 0회/단일 성공, 불일치 없음 |
| CT-13 | Negative | Voucher 작성자가 회계 승인 시도 | OA/SoD DENY |
| CT-14 | Negative | 회계조직 소속 아닌 일반 TEAM_LEAD 승인 | DENY |
| CT-15 | Negative | OA 회계승인 권한 해제 후 구 승인 WorkItem 재사용 | DENY |
| CT-16 | Negative | Business Approval만 있고 Accounting Approval 없음 | GL 0건 |
| CT-17 | Positive | Accounting Human Decision 후 ApproveAndPost 성공 | 회계승인 기록+Journal+Outbox 1회 COMMIT |
| CT-18 | Fault | EOS 승인 Proof Acceptance 기록 후 GL Line INSERT 예외 | EOS 전체 ROLLBACK, Candidate 유지; 선행 WC Human Decision 이력 보존 |
| CT-19 | Fault | Posting COMMIT 성공 후 HTTP 응답 유실 | 조회/대사로 기존 Journal 반환, 재기표 금지 |
| CT-20 | Race | 동일 Voucher에 대해 두 승인자 동시 Click | 원장 한 건만 POSTED |
| CT-21 | Race | 동일 IdempotencyKey + 다른 PayloadHash | 409 Conflict |
| CT-22 | Negative | POSTED Journal 직접 UPDATE/DELETE 시도 | DENY/DB 보호, Reverse Journal 필요 |
| CT-23 | Positive | 승인된 역분개로 POSTED 오류 정정 | 원본 불변, 새 Reverse Journal + 연결 |
| CT-24 | Positive | 급여 GL 집계 1건을 복수 Project로 배부 | 원천 합계와 배부 합계 대사 0차이 |
| CT-25 | Negative | 동일 Source GL 라인 2번 배부 또는 GL Transfer+관리배부 이중 합산 | 중복 적발/차단 |
| CT-26 | Boundary | 3개 이상 Project로 1원 단위 잔차 배부 | 결정적 잔차, 정확히 합계 보존 |
| CT-27 | Negative | 재고/미사용 부품을 입고 즉시 비용 처리 | 자산 유지, 소비·불용시 귀속 |
| CT-28 | Privacy | PM/PA가 월급/개인원가/소집단 역산 가능한 필터 질의 | DENY/안전 집계만 반환 |
| CT-29 | Recovery | GL POSTED 후 P&L Projection 소비 실패 | GL 유지, STALE 상태, idempotent rebuild |
| CT-30 | Regression | 기존 Golden A `VoucherDraft` / NSL v0.2 / WC Business Formal Approval | 기존 필수 골든 케이스 회귀 PASS |
| CT-31 | Negative | MyBee Agent가 EOS DB/GL에 직접 쓰려고 시도 | 차단; Canonical API+NSL WRITE만 허용 |
| CT-32 | Negative | Project 예산 링크(D12)에서 회계 금액 정본(D04)을 직접 갱신 | DENY/별도 D04 업무 필요 |
| CT-33 | Negative | PA가 본인 아닌 oa.user 요청자로 임의 기안 / 위임 증거 누락 | DENY, Delegation/Requester Evidence 강제 |
| CT-34 | Recovery | WC 회계승인 결정 완료 후 EOS Posting 이벤트 지연 | POSTING_SYNC_PENDING 투영, 동일 Operation 조회·재처리, GL 중복 없음 |
| CT-35 | Concurrency | OA Revocation과 Posting 직전 권한 검증 경합 | 최신 확인 가능한 권한 기준 fail-closed; 분산 TOCTOU 한계·감사 검사 |
| CT-36 | Negative | Project 생성 시 D12 관리 최소집합 5개 중 1개 누락 | Project 활성화 차단, 원본 필수 코드 유지 |

**Gate A Contract:** Schema + example + negative example validation; exact enum/reference/tenant/version/checksum.  
**Gate B DB:** 실제 PostgreSQL 트랜잭션, `FOR UPDATE`, optimistic CAS, UNIQUE, 원자 rollback/중복 racing.  
**Gate C Authority:** OA 회계역할, 계층, Project/Org/Tenant scope, 사전 business proof 및 Human Accounting Decision.  
**Gate D Accounting:** K-IFRS mapping, 차대·period·journal immutability·역분개.  
**Gate E Allocation:** payroll, purchase, shared cost, source conservation, GL/management exclusivity, rounding.  
**Gate F Compatibility:** NeX v2.1 Frozen Contracts, P8 Golden A, NSL v0.2 Tool/Approval/Replay, WC+EOS Approval Regression.

---

## 12. Implementation Dependency / Minimum Slice Plan (설계 결과)

| Slice | 구현 최소 범위 | 선행 Gate | 결과 |
|---|---|---|---|
| **CL-00 계약/정본 검증** | 원본 D04/D12 PDF 본문 대조, v2.1 Frozen Collision Check, 실제 K-IFRS 기반 계정표 확정 | 원본/계정표 | Contract FROZEN 후보 |
| **CL-01 Approval Binding** | ApprovedDocument Proof↔VoucherCandidate v2, source/attachment/amount envelope, D12 승인된 Project 바인딩 | C1 / OA/WC/EOS | 미승인 기안으로 전표 생성 불가 |
| **CL-02 Accounting Master** | account catalog/period, K-IFRS rule, posting rule, 신규 계정 생성 통제 | C3 | 유효한 분개검증 |
| **CL-03 Human Accounting Gate** | 회계담당자 신원·Scope/SoD, 회계 승인 WorkItem+Proof, exact voucher revision | C4 | 두 번째 사람 승인 입증 |
| **CL-04 Atomic GL Posting** | immutable journal, approval/post atomic UoW, unique/idempotency, outbox, reversal | C2/C5 | 확정 재무 원장, 실패 시 불완전 기표 0 |
| **CL-05 Project Allocation** | source pool/plan/lines, reconciliation, management-only mode, P&L Projection | C6 | GL와 Project 손익 연결 |
| **CL-06 D08 Payroll Extension** | 월총급여 GL + 개인정보 보호 인건비 Project 배부 | CL-04/05 | 인건비 관리손익 |
| **CL-07 D15 Purchasing Extension** | N Project→공용 발주 1회 결재→검수→매입 전표→배부/재고 | CL-04/05 | 구매·자재 관리손익 |

**권고 첫 Demo Success Path:** `D12 Project 생성/업무코드/Member → 기안 상신·최종 결재 → D04 Journal Candidate → 회계팀 승인 → Atomic GL Posting → 공용 비용 관리배부 → CEO Project P&L`.

---

## 13. Controlled Change / Open Issue Register

| 이슈 | 현재 판단 | Priority | Closure 증거 |
|---|---|---|---|
| OC-01 D04 v1.9 PDF 원문 대조 | **미완료** — Github binary 반환 차단. 연결 HTML로 cross-check | Blocker to full FROZEN | D04 page/section 별 승인·전표·계정코드 대조 |
| OC-02 D12 v2.8 PDF 원문 대조 | **미완료** | Blocker to full FROZEN | D12 Project Gate/업무코드/예산 권한 page/section 대조 |
| OC-03 K-IFRS 기반 실제 계정표 | 설계 정책 확인, **전체 코드 seed 원본 미확정** | Blocker to migration | 코드표·K-IFRS 항목 매핑 version/id 검증 |
| OC-04 기존 v1 VoucherDraft Proof optional | 반드시 신규 경로에서 필수화; **v1 계약 파괴 금지** | Critical | v2 schema+positive/negative Golden A 회귀 |
| OC-05 EOS Accounting Authorization | 기존 조직장 직책만으로 불충분, OA 회계권한 필요 | Critical | 회계 팀장만 PASS, 일반 TEAM_LEAD DENY |
| OC-06 GL Posting Aggregate | 기존 Draft와 분리한 신규 EOS SoR 필요 | Critical | migrations, command, OpenAPI, DB race tests |
| OC-07 Shared company-scoped voucher | 기존 Project 필수 header와 공유 원가 충돌 | High | 회사 단위 source pool/journal 설계·회귀 |
| OC-08 Allocation vs GL cost transfer | Phase-1 MANAGEMENT_ALLOCATION 우선 | High | 동일 원천의 exclusive-mode tests |
| OC-09 Payroll planning Grade Rate vs actual | 등급별 공개 계획 vs 개인 실제 원가 분리 | High | privacy+reconciliation negative tests |
| OC-10 운영 모델: ApproveAndPost sync | Phase-1 동기식 Local Atomic Commit; 비동기 확장은 별도 ADR | High | timeouts, API status, recovery gate |
| OC-11 Source Audit of existing EOS | 위 일부 경로 검토됨. 전체 수백 구현 파일의 회귀·서비스 API audit는 별도 수행 | High | EOS Source Audit + SRS Traceability |

**Change Rule:** NeX Frozen Architecture 변경 필요가 발견되면 MyBee 문서가 자동으로 우선하지 않는다. `Open Issue → Controlled Amendment Candidate → Authority Review → Approval` 후에만 변경한다.

---

## 14. Source Traceability / Pinned Revision

### NeX (실제 GitHub 코드/문서 본문 확인)

- NeX Platform: `nurigitdev/2607_nex_platform` / `master` / HEAD `c2c03b20e22691cc1984f044e0cacd5d698f9bd3` (2026-11-08 06:31:52 UTC)
  - `docs/frozen/v2.1/10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md`
  - `database/nex-eos/migrations/2505_eos_account.sql`
  - `database/nex-eos/migrations/2506_eos_voucher_draft.sql`
  - `database/nex-eos/migrations/2509_eos_approval_policy.sql`
  - `database/nex-eos/migrations/2510_eos_approval_instance.sql`
  - `database/nex-eos/migrations/2511_eos_approval_proof.sql`
  - `services/nex-eos/nex_eos/business_transactions.py`
  - `services/nex-eos/nex_eos/voucher_commands.py`
  - `services/nex-eos/nex_eos/vouchers.py`
  - `services/nex-eos/nex_eos/approval_transitions.py`
  - `contracts/schemas/service/nex_eos/create_voucher_draft_command.v1.schema.json`
  - `contracts/openapi/nex-eos.openapi.yaml`
  - `database/README.md`
- NSL v0.2: `nurigitdev/2608_nsl` / `master` / HEAD `f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4`; `README.md`에서 단일 Controlled WRITE, Approval/Commit/Replay, Tool Port 검증.

### MyBee (GitHub HTML 본문 확인 / PDF는 파일 존재만 확인)

- MyBee: `nurigitdev/2611_MyBee_Blueprint` / `main` / HEAD `948b50fd43fc4e0f0d3f40ffd6335871ec741559` (2026-11-08 09:34:59 UTC)
- **HTML 본문 확인**
  - `docs/origin/MyBee_Intent_SLM_20업무영역_상세설계_v4.7.html` (D04/D12 코드/실행 의미)
  - `docs/origin/MyBee_업무영역_차수별오픈방안_v1.16.html` (D04 account/회계 코드, D12 project코드/예산 경계; 이전 차수 모델)
  - `docs/origin/MyBee_프로젝트인건비예산집행_설계서_v1.7.html` (D04/D12 예산 SoR, 집행·배부, 개인정보)
  - `docs/origin/MyBee_공용비용_통합결재_설계요약_v1.1.html` (공용 구매/급여/비용 원가배부)
  - `docs/origin/MyBee_공용부품_통합구매결재_설계요약_v1.0.html` (공용구매 N Project→한 발주/결재)
  - `docs/origin/MyBee_DB설계방향서_v2.11.html` (계정/분개/원장 논리 표, 정본 원칙)
  - `docs/origin/MyBee_프로젝트생성신청_자료·UI설계서_v1.12.html` (Project 기안/템플릿/계정/예산)
  - `docs/origin/MyBee_D19_프로젝트기획생성_업무코드명세서_v1.2.html` (D12의 프로젝트 관리 필수 5코드 원칙)
- **PDF 존재·sha 확인, 본문 미확인**
  - `docs/origin/MyBee_업무스킬설계서_D04_회계업무_v1.9.pdf`: Git blob `d2f164bcc4f60fc8c1e43b0c3b0a28253c608021` / 7,570,040 bytes
  - `docs/origin/MyBee_업무스킬설계서_D12_프로젝트수행업무_v2.8.pdf`: Git blob `e8a5ec68150f98401bd70739119fe8fa6088bfb7` / 7,118,923 bytes


### 주요 고정 revision 직접 링크

- [D04 회계업무 PDF v1.9](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%EC%97%85%EB%AC%B4%EC%8A%A4%ED%82%AC%EC%84%A4%EA%B3%84%EC%84%9C_D04_%ED%9A%8C%EA%B3%84%EC%97%85%EB%AC%B4_v1.9.pdf) — 파일 존재 확인 / 본문 미확인
- [D12 프로젝트수행 PDF v2.8](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%EC%97%85%EB%AC%B4%EC%8A%A4%ED%82%AC%EC%84%A4%EA%B3%84%EC%84%9C_D12_%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8%EC%88%98%ED%96%89%EC%97%85%EB%AC%B4_v2.8.pdf) — 파일 존재 확인 / 본문 미확인
- [MyBee D19 필수 코드](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_D19_%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8%EA%B8%B0%ED%9A%8D%EC%83%9D%EC%84%B1_%EC%97%85%EB%AC%B4%EC%BD%94%EB%93%9C%EB%AA%85%EC%84%B8%EC%84%9C_v1.2.html) — 본문 확인
- [MyBee 인건비·예산·배부](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8%EC%9D%B8%EA%B1%B4%EB%B9%84%EC%98%88%EC%82%B0%EC%A7%91%ED%96%89_%EC%84%A4%EA%B3%84%EC%84%9C_v1.7.html) — 본문 확인
- [MyBee 공용비용 원가배부](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%EA%B3%B5%EC%9A%A9%EB%B9%84%EC%9A%A9_%ED%86%B5%ED%95%A9%EA%B2%B0%EC%9E%AC_%EC%84%A4%EA%B3%84%EC%9A%94%EC%95%BD_v1.1.html) — 본문 확인
- [NeX Frozen Architecture Authority](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/docs/frozen/v2.1/10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md) — 본문 확인
- [NeX EOS Approval Proof SQL](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/database/nex-eos/migrations/2511_eos_approval_proof.sql) — 본문 확인
- [NeX EOS Voucher Command v1 JSON Schema](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/contracts/schemas/service/nex_eos/create_voucher_draft_command.v1.schema.json) — 본문 확인
- [NeX EOS Voucher Draft SQL](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/database/nex-eos/migrations/2506_eos_voucher_draft.sql) — 본문 확인

## 15. Sign-off / Change Control

**Contract Authoring Result:** C1~C6의 구조와 불변조건/Negative Acceptance Tests 확정 **제안**.  
**본 문서 상태:** `v1.0-RC1`, 최종 서명/Freeze 아님.  
**Full Closure 조건:** (a) D04/D12 PDF 직접 대조, (b) MyBee 계정과목 seed 원본 확정, (c) NeX EOS Source Audit의 충돌 검토, (d) 계약 스키마 + PostgreSQL DB + 승인/권한/Allocation Golden Gate 통과.  
**다음 문서 권고:** `NeX_MyBee_D04_D12_EOS_Source_Audit_and_Gap_Analysis_v1.0.md` → `NeX_MyBee_D04_D12_Pre_Architecture_Decision_v1.0.md` → `NeX_MyBee_D04_D12_EOS_SRS_v1.0.md` → `NeX_MyBee_Phase1_InRepo_Deferred_EOS_ADR_v1.0.md` → `NeX_MyBee_Implementation_Slice_Plan_v1.2.md`.
