# NeX–MyBee D04/D12 EOS Pre-Architecture Decision v1.0

**문서 ID:** `NEX-MYBEE-EOS-PAD-D04D12-20261109`  
**문서 유형:** Pre-Architecture Decision (PAD) / 설계 의사결정 기준선  
**작성일:** 2026-11-09 (Asia/Seoul)  
**상태:** `DESIGN DECISION BASELINE — SRS-READY / IMPLEMENTATION NOT YET ACCEPTED`  
**우선순위:** `NeX Platform v2.1 Frozen Architecture > NeX-EOS Canonical Contract > MyBee Business Domain Requirement`  
**변경 정책:** Frozen 설계·NSL Compiler/Runtime·P8/Golden A v1 Contract를 직접 변경하지 않는다. 신규 기능은 EOS 소유 Aggregate와 버전형 API/Tool Binding으로 추가한다.  
**검토 기준:** Source Audit & Gap Analysis v1.0, Accounting Transaction Contract Closure v1.0-RC1 (C1~C6).  
**주의:** 본 문서는 설계상 선택을 고정하는 **PAD 의사결정안**이다. 제품 코드의 적용·실 DB PASS·회계 규정 적합성까지 완료되었다는 의미가 아니다. `D04 v1.9.pdf / D12 v2.8.pdf` 파일 존재는 확인되었으나 PDF 본문 직접 추출/페이지 대조는 미완료이다. 대조 가능한 MyBee HTML 및 NeX/NSL 실제 소스를 근거로 작성했다.

---

## 0. Executive Decision

### 0.1 최종 아키텍처 방향

> **NeX는 Enterprise Agent Platform이고, MyBee는 NeX v2.1 위에서 동작하는 사무업무 Domain AX Service이다.** MyBee 설계의 업무코드·정책·업무흐름을 수용하지만 MyBee가 별도 Agent Runtime, 승인 엔진, 결정적 실행 엔진, 회계 정본 DB를 NeX 위에 중복 구현하지 않는다.

1. **회계 SoR는 `nex-eos` 한 곳**에 둔다. `WC`는 업무와 인간 결재 WorkItem, `OA`는 실시간 신원·권한, `AE/NSL v0.2`는 승인/신뢰가 보호된 단일 결정적 WRITE, `WA`는 증적·Artifact를 소유한다.
2. **모든 MyBee 신규 전표는 사전에 승인된 기안·품의서에 귀속**시킨다. 이후 회계 담당자가 전표 Revision을 검토·승인해야 GL Posting이 가능하다. `업무 결재 완료 ≠ 회계 승인 완료 ≠ GL 기표 완료`.
3. **기존 `eos_voucher_draft`와 Golden A v1은 수정 없이 유지**한다. `MyBee Finance v2`는 승인필수 `VoucherCandidate`와 `PostedJournal`을 신규 Aggregate로 둔다. v1 Draft 성공을 GL Posting의 사전 승인으로 간주하지 않는다.
4. **회사(Legal Entity) 단위 공용전표와 여러 Project 귀속은 분리**한다. 승인 전표의 주체는 회사, Project별 원가는 `Project Allocation Ledger`의 배부 명세로 표현한다. 기존 `project_id NOT NULL` 승인/전표에 가짜 Project ID를 넣지 않는다.
5. **Posting은 EOS 내부의 단일 PostgreSQL Unit of Work에서 원자적**으로 완료한다. 회계 Human Decision 증명 수용, GL header/lines, Candidate 전이, 승인문서 사용량, Idempotency, BusinessOperation, Outbox가 부분 Commit되어서는 안 된다.
6. **관리손익은 POSTED GL에서만 확정 실적을 계산**한다. 직접 귀속 또는 관리배부 중 하나만 인식한다. 승인되었지만 미기표된 금액과 계획/예측은 별도 화면 열로 제공한다.
7. **급여·구매는 동일한 원장/배부 Contract의 Domain Adapter**다. 회사/그룹 급여 합계·공용 발주 한 건을 Project에 나누되 원천 거래·개인정보·재고자산 인식 규칙을 보존한다.

### 0.2 설계 결정 상태

- **PAD 결정:** ADR-01~ADR-15는 이후 SRS/구현계획을 작성하는 기준선으로 사용한다.
- **별도 검증 Gate:** PDF 원문 정합성, K-IFRS 기초 계정표 원본·버전, 법인별 권한 정책, 실제 PostgreSQL Fault/Race Test, 기존 Golden A/NSL 회귀.
- **변경 요구:** Frozen과 충돌하는 새로운 요구는 이 문서로 임의 승인하지 않는다. Controlled Amendment Candidate로 기록하고 별도 거버넌스를 따른다.

---

## 1. Authority & Non-negotiable Invariants

| 항목 | 최종 Authority / SoR | 지켜야 할 경계 |
|---|---|---|
| Agent Registry / IA·PA·EA | NeX-AE Agent Runtime | MyBee에서 Agent Runtime 독립 구현 금지 |
| 업무 조정, WorkItem, Human Workflow | NeX-WC | 승인 WorkItem은 재무 원장 정본이 아님 |
| 신원·역할·권한·Scope·현재 승인자 | NeX-OA | LLM/업무코드가 스스로 승인권 생성 금지 |
| 서명된 Skill·NSL 단일 Controlled WRITE | AE Gateway + NSL v0.2 | NSL 내부 SQL/Workflow/Distributed Tx 추가 금지 |
| 기업의 업무 승인 Proof·회계 데이터·GL·예산·배부 | NeX-EOS | 타 서비스의 회계 금액 정본 Write 금지 |
| 증빙 원본·업무 산출물 | NeX-WA / 승인된 Artifact Store | 원장에는 버전·ID·해시 참조만 저장 |
| MyBee 업무코드·스킬 조합·문서 양식·정책 | MyBee AX Domain Service | Domain Operation은 EOS의 권한/트랜잭션 규약을 통과 |
| Model Context / Generation | CX / MO | LLM의 숫자·회계 판정을 Posting 정본으로 사용 금지 |

**AR-01** `tenant_id` 및 법인/Project/문서/계정의 정합성이 모든 회계 WRITE에 존재해야 한다.  
**AR-02** 서로 다른 서비스 DB를 하나의 전역 ACID 트랜잭션으로 다루지 않는다. 통합 업무는 Saga/Outbox/Inbox/Idempotency/상태 대사로 보장한다.  
**AR-03** 회계 장부는 append-only PostedJournal과 역분개로 정정한다. 게시된 금액의 임의 UPDATE/DELETE 금지.  
**AR-04** GL과 Allocation을 중복 수익·비용으로 합산하지 않는다.  
**AR-05** 생성 당시 승인과 Posting 당시 승인·권한·원천 데이터 검증을 분리하되, 승인된 정확한 Revision/해시에만 기표한다.  
**AR-06** 기존 `FINANCE.CREATE_VOUCHER_DRAFT` 및 Frozen NSL 계약의 의미를 변형하지 않는다.

---

## 2. Source Audit Findings — PAD의 직접 근거

기준 Revision(읽기 전용):

| Repository | Branch / Commit | 근거 |
|---|---|---|
| `nurigitdev/2607_nex_platform` | `master` / `c2c03b20e22691cc1984f044e0cacd5d698f9bd3` | Frozen Closure, EOS migrations `2500~2515`, EOS 서비스 38 Python modules, EOS OpenAPI/JSON Schema, AE NSL Binding, 테스트 파일 |
| `nurigitdev/2608_nsl` | `master` / `f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4` | NSL v0.2 Tool Contract와 Voucher/Project Skills |
| `nurigitdev/2611_MyBee_Blueprint` | `main` / `948b50fd43fc4e0f0d3f40ffd6335871ec741559` | MyBee 프로젝트 인건비 v1.7, 공용비용 v1.1, D19 v1.2, 차수별 오픈 v1.16 등 HTML; D04/D12 PDF 존재 확인 |

**소스에서 직접 확인된 상태:**

- `2505_eos_account.sql`: 회사별 계정표 버전/과목 계층/Posting 허용 Leaf 구분 없는 최소 계정과목 모델.
- `2506_eos_voucher_draft.sql`: `eos_voucher_draft.project_id NOT NULL`; `state = 'DRAFT'` DB CHECK. `eos_voucher_draft_line`의 `signed_amount`; GL Posting 원장 테이블 아님.
- `vouchers.py`: 계정·Project ACTIVE/유효기간 및 차대 균형 검증 있음. 회계기간·확정 원장 기능 없음.
- `2510_eos_approval_instance.sql`: EOS `BUSINESS_FORMAL` ApprovalInstance의 `project_id NOT NULL`, `requester_ref_type = oa.user` 제한. 회사 공용 구매/급여 승인에 그대로 사용할 수 없음.
- `2511~2512`: 불변 Final `eos_approval_proof`와 실제 WC Decision의 바인딩 존재. **Proof를 신규 MyBee 경로에서 실제 검증하는 연결**이 필요.
- AE `nsl_eos_write_execution.py`: 기존 v1 VoucherDraft 명령은 `business_approval_proof_ref: None`을 명시적으로 조립. 이는 **MyBee의 승인 필수 요구와 충돌하지만 Golden A 유지 계약**이므로 기존 기능 삭제 불가.
- `2501_eos_business_transaction_core.sql`, `business_transactions.py`: EOS BusinessOperation/Idempotency/Transactional Outbox를 단일 Commit에서 운용하는 기반 존재. 이벤트 타입은 확장 필요.
- `2504_eos_project_hierarchy.sql`, `2514_eos_project_member.sql`: Project 3계층, NVTProject, Member 존재. Project 필수 업무코드·Business Ready Gate·Grade/MD 및 Project별 예산/원가 배부는 미구현.
- EOS active route/source에서는 PostedJournal, AccountingPeriod, Allocation/P&L SoR와 API를 확인하지 못함. **이 평가는 해당 Revision의 정적 Source Audit 범위에 한정**한다.

**MyBee 원문 확인 범위 제한:** PDF 파일 존재는 확인하였으나 7MB급 `D04 v1.9.pdf`, `D12 v2.8.pdf`의 페이지별 본문은 연결 도구의 바이너리 조회 제한으로 직접 검증하지 못했다. 따라서 신규 계약의 원문 100% 일치·특정 조항 완결은 주장하지 않으며 `GATE-SRC-PDF`를 유지한다.

---

## 3. ADR Register — v1.0 결정

| ID | 결정 | 승인 수준 | 연결 Gap |
|---|---|---|---|
| **PAD-ADR-01** | Frozen NeX 책임/승인/NSL/DB 경계 유지, MyBee는 Domain AX Service | DECIDED | G01~G18 |
| **PAD-ADR-02** | EOS에 Legal Entity Accounting Scope 및 Project-Company Binding 추가 | DECIDED | G08, G14 |
| **PAD-ADR-03** | K-IFRS 기반 회사 계정표와 회사별 Posting Policy 분리·버전 관리 | DECIDED | G07, G05 |
| **PAD-ADR-04** | D12 5개 필수 업무코드 및 Project `BusinessReady` Overlay | DECIDED | G09, G10, G16 |
| **PAD-ADR-05** | 승인 기안/품의의 불변 DocumentEnvelope + 사용량 관리 | DECIDED | G01 |
| **PAD-ADR-06** | 기존 Golden A v1 Draft 보존, MyBee 승인필수 Candidate v2 신설 | DECIDED | G01, G02, G14 |
| **PAD-ADR-07** | 회사/복수 Project 승인범위의 EOS Scoped ApprovalCase v2 (WC/OA 재사용) | DECIDED | G08 |
| **PAD-ADR-08** | 업무 결재와 별도의 Accountant Human Approval + SoD + exact Revision | DECIDED | G03 |
| **PAD-ADR-09** | EOS PostingAcceptance+PostedJournal+Operation/Outbox 단일 DB Commit | DECIDED | G04, G05, G13 |
| **PAD-ADR-10** | GL Journal 불변·분개 균형·기간 Lock·역분개만 정정 | DECIDED | G04, G05 |
| **PAD-ADR-11** | `MANAGEMENT_ALLOCATION` 우선, GL Cost Transfer와 상호 배타 | DECIDED | G06, G14 |
| **PAD-ADR-12** | GL Source Pool → AllocationPlan/Batch/Line, 금액 보존·결정적 반올림 | DECIDED | G06, G17 |
| **PAD-ADR-13** | D04 Budget SoR + D12 배정 Link, Project P&L 투영/보안 | DECIDED | G11, G15 |
| **PAD-ADR-14** | NSL Tool과 EOS API는 신규 버전/Binding만 추가, 기존 v1 불변 | DECIDED | G12 |
| **PAD-ADR-15** | 승인·기표·배부는 별도 사건이며 Unknown Commit은 조회/대사, 미기표는 미확정 | DECIDED | G04, G13, G17 |

**Decision 충돌 처리:** 기술 제약 때문에 특정 ADR을 구현할 수 없으면 이 PAD를 몰래 우회하지 않고 `Implementation Blocker → ADR Amendment Request → Architecture Review` 순서로 처리한다.

---

## 4. EOS Aggregate & Data Ownership (PAD-ADR-02/04/05/06/09/11/13)

### 4.1 Aggregate 구성 — 기존 유지와 신규

| Aggregate / 데이터 객체 | 소유 | 조치 | 핵심 책임 |
|---|---|---|---|
| `eos_business_operation`, `eos_idempotency`, `eos_outbox` | EOS | **REUSE** | 업무 명령 ID, 동일 결과 재사용, 원자적 이벤트 생성 |
| `eos_project`, `eos_nvt_project`, `eos_project_member` | EOS | **REUSE / EXTEND OUTSIDE** | Project 계층, 사용자/PA Membership. 기존 테이블 의미 보존 |
| `eos_account` | EOS | **REUSE** | 기존 계정과목 식별 및 기본 코드, P8 Resolver 호환 |
| `eos_voucher_draft`, `_line`, 기존 첨부 | EOS | **KEEP v1** | Golden A 및 P8 기존 Draft E2E |
| `eos_approval_policy`, `_instance`, `_decision`, `_proof` | EOS | **REUSE** | 기존 Project-scoped BUSINESS_FORMAL 승인·Proof. 기존 PK/FK/해시 계약 유지 |
| `eos_legal_entity`, `eos_project_company_binding` | EOS | **NEW** | 회사(법인)와 Project 소유관계; 공용전표 Anchor. 임의 Project Anchor 금지 |
| `eos_account_catalog_release`, `eos_company_account_policy`, `eos_posting_rule_release` | EOS | **NEW** | 검증된 K-IFRS 기준 계정표 버전, leaf/postable, 회사별 유효성/규칙 |
| `eos_accounting_period` | EOS | **NEW** | 법인별 회계기간 OPEN/CLOSING/CLOSED, 기표와 마감 동시성 |
| `eos_approved_document_envelope`, `_consumption` | EOS | **NEW** | 승인된 기안·품의 문서 Revision/Hash/증빙/한도/잔액의 회계 이용 계약 |
| `eos_voucher_candidate`, `_revision`, `_line` | EOS | **NEW** | 회사 단위 승인필수 전표의 검토 대상과 불변 Revision |
| `eos_scoped_approval_case`, `_subject_binding` | EOS | **NEW / shared adapter** | 회사/Project 집합/단일 Project 범위의 **범용 EOS Formal ApprovalCase v2**. 동일 WC/OA 승인 기반 사용, MyBee 독자 엔진 금지 |
| `eos_accounting_approval_acceptance` | EOS | **NEW** | ACCOUNTING_POSTING 목적의 사람 결재를 특정 Candidate Revision에 수용한 불변 증명 |
| `eos_journal_header`, `eos_journal_line` | EOS | **NEW** | 회사 차원의 유일한 회계 GL PostedJournal SoR |
| `eos_gl_balance_projection` | EOS | **NEW (derived)** | 원장으로부터 재구축 가능한 계정 잔액 Projection; 금액 정본 아님 |
| `eos_cost_source_pool`, `eos_cost_allocation_plan`, `_batch`, `_line`, `_adjustment` | EOS | **NEW** | Posting된 적격 원가/수익의 Project 귀속·근거·조정 불변 기록 |
| `eos_budget`, `eos_project_budget_binding`, `eos_budget_execution_projection` | EOS | **NEW** | D04 예산 금액의 정본, D12 배정 관계, 실적은 Posted 데이터 투영 |
| `eos_project_work_code_set`, `eos_project_work_assignment`, `eos_project_business_readiness` | EOS | **NEW** | D12 업무코드 버전·수행자·의무 5개 준비·BusinessReady |
| `eos_project_pnl_projection` | EOS | **NEW (derived)** | Project/NVT 손익/예산/미배부/신선도 및 민감정보 통제된 조회 |
| 승인된 문서 원본/첨부 Binary, 실적 업무 Artifact | WA / 승인된 Blob Store | **REUSE** | EOS는 `artifact_ref`, 해시, immutable version과 policy를 검증하여 참조 |

**핵심:** `eos_journal_header`와 `eos_journal_line`이 **유일한 GL 회계 금액 정본**이다. `eos_cost_allocation_line`은 관리 귀속 정본이지만 재무 회계 계정잔액의 두 번째 정본이 아니다. GL 잔액과 P&L Projection을 분리해야 이중 집계를 막는다.

### 4.2 DB 구성과 Cross-Service 경계

- EOS 자체 소유 데이터끼리는 `(tenant_id, id)` 복합 FK를 사용할 수 있다. EOS↔WC/OA/WA 간 직접 DB FK/JOIN은 만들지 않는다. 외부 Decision/Artifact는 안정된 ID·Hash·Proof Snapshot으로 연결한다.
- 현재 `eos_project`와 `eos_account`는 `tenant_id` 기반의 기존 v1 객체다. **기존 Project를 파괴적 변경하지 않고** `eos_project_company_binding`과 `eos_company_account_policy`로 법인·기간·허용정책을 추가한다.
- `eos_legal_entity`는 회계 주체인 회사로서 법인코드, 기준통화, 회계연도 정책을 가진다. `eos_org_unit(type=COMPANY)`는 조직 계층이므로 회계 법인 ID로 암묵 대체하지 않는다. 연결이 필요하면 검증된 바인딩을 사용한다.
- `tenant_id`와 `company_id`를 혼동하지 않는다. 단일 법인 고객도 명시적 ID를 갖게 하며 향후 복수 법인에도 범위가 명확해야 한다.
- 각 신규 테이블은 `created_at`, 변경 버전/승인 근거, 감사 사건, tenant-isolated 유니크 제약을 가진다. 실행상 유효시간과 결재 당시 Snapshot을 서로 구분한다.

### 4.3 Aggregate Consistency Boundaries

| Aggregate Boundary | Lock/CAS 대상 | 원자적 결과 | 다른 서비스와의 관계 |
|---|---|---|---|
| `BusinessApprovalEnvelope` | 승인된 문서 Revision/사용한도 | Document usage 증가 또는 신규 승인필요 결정 | WC Decision 수신, WA 문서 해시 검증 |
| `VoucherCandidate` | Candidate ID / Revision | 회계검토 대상 불변 Snapshot, 상태 변경 | MyBee·AE가 명령 제안 |
| `AccountingApprovalCase` | Case/Revision, WC Evidence ID | 승인/거절/무효 이벤트·증거 보존; 기표 여부는 별도 | OA Scope + WC WorkItem |
| `AccountingPosting` | Candidate Revision, Period Row, 승인 사용량, idem key | **ApprovalAcceptance + PostedJournal + Candidate POSTED + Outbox** 단일 Commit | NSL 단일 WRITE / EOS API |
| `CostAllocationBatch` | SourcePool/Plan Version / idem key | AllocationBatch/Lines/Conservation/Audit + Outbox Commit | MyBee 비용 근거/WA Work Evidence 읽기 |
| `BudgetCommit` | D04 Budget version | 예산 편성·변경·승인 흔적 한 Commit | D12 Project는 Link만 보유 |
| `ProjectPnlProjection` | projector watermark | 원장 기반 파생 상태 갱신 | 경영진/PA 권한 분리 API |

---

## 5. Company/Shared Voucher & Human Approval (PAD-ADR-05/07/08)

### 5.1 공용전표 승인 Scope — 최종 선택

**Decision: `LegalEntity Scoped ApprovalCase v2`**. 이유는 기존 승인 `eos_approval_instance.project_id NOT NULL`을 무단으로 NULL 허용하거나 가짜 프로젝트에 비용을 꽂으면 감사/손익 의미가 뒤틀리기 때문이다.

**입력/대상 모델(논리 계약):**

```text
ScopedApprovalSubject {
  tenant_id: UUID-or-canonical-tenant-id
  company_id: LegalEntityId               # REQUIRED
  approval_domain: BUSINESS_FORMAL         # 기존 Frozen Domain 의미 보존
  approval_purpose: DOCUMENT_SIGNOFF | ACCOUNTING_POSTING
  scope_type: COMPANY | PROJECT | PROJECT_SET
  project_ids: [] | [ProjectId...]         # 회사와 동일 법인인지 검사; 회사 범위는 빈 배열 허용
  protected_subject_ref: DocumentRevisionRef | CandidateRevisionRef
  protected_subject_hash: sha256
  approval_policy_ref: policyId + version + hash
  requested_by_ref: validated Human Principal
  effective_authorization_ref: OA decision/revision/checked_at
}
```

**운용:**
1. 회사 공용 급여/공용 구매의 **기안/품의는 하나**이다. `scope_type=COMPANY` 또는 복수 프로젝트 명세가 첨부되면 `PROJECT_SET`; 각각의 Project 실사용 분담은 문서 라인 또는 Allocation Plan으로 정한다.
2. 기존 WC `ApprovalWorkItem`/결정/전달/재전송 및 OA 권한 판정을 재사용한다. EOS는 `scope_type`과 `approval_purpose`를 가진 **v2 Subject Binding**을 추가해 기존 `BUSINESS_FORMAL` Proof와 동일한 보안 강도의 불변 결정 Chain/Hash를 사용한다.
3. **새로운 독립 승인 엔진을 만들지 않는다.** 회사 범위 수용이 현행 v1 DB 제약으로 불가능한 지점만 EOS 소유 `ScopedApprovalCase v2` Adapter/Storage를 추가한다. WC/OA/NSL Frozen semantics는 변경하지 않는다.
4. 기존 Project-scoped `eos_approval_instance`/Proof v1은 유지하고, 신규 Company/ProjectSet Approval는 v2 Contract만 사용한다. 두 Proof 형식의 오용·다운캐스팅 금지.
5. 회사 범위 담당자는 `OA finance:journal:approve`와 법인 권한, 지정된 회계조직/승인 지위, 책임 분리를 **동시에** 만족해야 한다. 단지 `TEAM_LEAD` 역할만으로 자동 승인권을 갖지 않는다.

**실제 EOS v2 계약은 SRS에서 타입, Hash, 정책 선택, unique/cas, REST path를 정한다.** 설계상 Scope 해결은 완료되었으나, SRS 단계에서 통합 테스트로 검증해야 한다.

### 5.2 기안·품의 `DocumentApprovalEnvelope`

기안·품의 최종 승인 시 EOS 승인 정본은 다음을 보존한다.

| 필드 | 내용 / 불변 조건 |
|---|---|
| `tenant_id, company_id, approved_document_id, revision` | 회사/버전 정본; 다른 법인 전표로 재사용 불가 |
| `document_type, business_code, source_operation_ref` | 지출결의/구매품의/급여총액 확정 등 업무 근거 |
| `document_content_hash, attachment_manifest_hash` | 결재자가 본 문서·첨부의 정확한 버전. 바뀌면 재승인 |
| `business_approval_proof_ref, proof_hash, policy_version` | EOS가 검증한 Final BUSINESS_FORMAL Proof |
| `approved_amount, currency, approved_scope` | 승인 금액/대상; 분할 사용한도 검증 |
| `effective_period, expires_at, status` | 유효기간, 취소/정정/만료 상태 검증 |
| `consumption_ref, consumed_amount, remaining_amount` | 여러 전표가 한 승인문서를 사용하는 경우 이중 지출 방지 |

**Approval Use:** 한 품의에서 부분 납품/분할 청구를 허용하더라도 `sum(consumed_amount) <= approved_amount`가 성립해야 한다. `eos_approved_document_consumption`에 업무적으로 안정된 출처라인/증빙/청구 ID와 unique 제약을 두고 EOS DB Tx에서 잠금·사용량 처리한다. 동일 Invoice/회계 증빙을 다른 Candidate로 반복 소비하지 않는다.

**수정 원칙:** 승인 문서/금액/ProjectSet/근거·첨부의 중요 부분이 바뀌면 이전 Proof로 기표 금지; 새 문서 Revision을 상신·결재한다. 허용 오차/잔액 기준은 별도 승인된 `DocumentTolerancePolicy`로만 적용한다.

### 5.3 회계 Human Approval & Separation of Duties

**Decision:** 회계 승인 `FL0004008`은 사업 기안 결재와 **별도 Human Gate**, 기표 `FL0004009`는 그 결정의 검증/수용 후 결정적 EOS WRITE이다.

- 회계 승인 대상: `candidate_id`, `candidate_revision`, `candidate_hash`, `document_envelope_hash`, 승인 적용 법인·계정·회계기간·차변/대변·원천 증빙.
- Approver: OA의 현재 유효한 `finance:journal:approve` Scope 및 회사/회계업무 책임 검증, 사전 결재권과 **분리**.
- 기본 SoD: `requester != accountant_approver`, `candidate_preparer != accountant_approver`; Phase-1에서는 동일인이 업무 결재와 회계 승인까지 단독 종료하지 않도록 정책상 별도 승인자 강제. 관련 예외/대체 승인자는 향후 통제된 정책으로만 설계한다.
- 회계 승인이 완료되어도 WC Event만으로 `POSTED` 표기하지 않는다. `accounting_approval_event = APPROVED`와 `posting_state = SYNC_PENDING`은 가능한 일시적 상태다.
- Post 전에 OA 권한 최신 검증 증거(Revision, Hash, checked_at), 회계기간 Open, 계정유효성, 문서 Revision, Candidate Hash 일치를 Fail-Closed로 확인한다.
- 회계 승인 직후 원천 Candidate 변경, 승인권 철회, 기간 마감·상태 변경은 Posting 거부하고 `STALE_REVIEW/REVALIDATION_REQUIRED`로 재심의한다.
- 회계 결정은 사람이 내린다. NSL `approve`는 WRITE 실행 Human Gate로서 별도이며, 이 결정과 바꿔치기하지 않는다.

**No Project Faking:** `eos_voucher_draft.project_id`와 `eos_approval_instance.project_id`의 필수 제약을 우회하려고 `OPERATING` 프로젝트를 가짜 법인 원천에 붙이지 않는다. `OPERATING` 프로젝트는 **실제 미배부 원가의 귀속 대상**으로는 사용 가능하지만 승인 Scope의 형식적 대체물이 아니다.

---

## 6. Voucher State & Posting Transaction (PAD-ADR-06/09/10/15)

### 6.1 별도 상태 머신

**Document Workflow (Business Signoff):**
`DRAFT → SUBMITTED → IN_APPROVAL → APPROVED | REJECTED | RETURNED | WITHDRAWN`.

**MyBee v2 Voucher Candidate:**

| 현재 상태 | 입력/증명 | 다음 상태 | 회계 분개 정본? |
|---|---|---|---|
| 없음 | 승인된 Document Envelope + v2 create | `DRAFT` | 아니오 |
| `DRAFT` | 분개/계정/회계기간 검증 | `READY_FOR_REVIEW` | 아니오 |
| `READY_FOR_REVIEW` | 회계 Review WorkItem 생성 | `ACCOUNTING_REVIEW_PENDING` | 아니오 |
| `ACCOUNTING_REVIEW_PENDING` | 담당자 반려 | `RETURNED` | 아니오 |
| `RETURNED` | 정정 후 새 Revision, 검증 | `READY_FOR_REVIEW` | 아니오 |
| `DRAFT/READY/RETURNED` | 승인된 취소 절차 | `CANCELLED` | 아니오 |
| `ACCOUNTING_REVIEW_PENDING` | 최종 Human Approval + EOS Posting 성공 | `POSTED` | **예** |

`ACCOUNTING_APPROVED_PENDING_POST`는 WC Human Decision은 완료되었으나 EOS에서 Posting되지 않은 상태를 나타내는 **cross-service 관측 Projection**이다. `POSTED`와 혼동하지 않으며 필요 시 전달지연/복구 상태를 포함한다.

**PostedJournal:** `POSTED`는 행 불변. 잘못된 전표는 `FL0004010`로 원 전표를 참조한 **새 역분개 전표**를 만든다. 원 전표는 POSTED 상태와 식별자를 유지한다. 조회에서 `reversed_by` 관계와 `net_effect`를 제공할 수 있으나 원행을 수정하지 않는다.

### 6.2 `FINANCE.VOUCHER.APPROVE_AND_POST` Logical Contract

| 요소 | 계약 |
|---|---|
| Input | tenant/company/candidate_id/revision/hash, business approval proof/envelope, accounting Human Decision Proof & OA evidence, rule/account/period refs, business_operation_id/idempotency_key/payload_hash |
| Deterministic checks | Candidate revision, Document hash/limits, approved status, accounting approver SoD, account active/leaf, period OPEN, source economic classification, `Σdebit=Σcredit`, FX/currency coherence |
| Output (`COMMITTED`) | immutable `journal_id`, posting seq/period, `business_transaction_ref`, event ref, exact candidate/approval refs, hash, reconciliation/verification refs |
| Output (`CONFLICT/REJECTED`) | 안정된 error code, **POSTED journal 0건** |
| Uncertain result | `UNKNOWN_COMMIT_STATE` / reconciliation reference; 새로운 키로 재제출 금지 |
| Replay | 같은 idem key+payload hash는 원 결과; 동일 key+다른 payload hash는 `409 IDEMPOTENCY_CONFLICT` |

### 6.3 EOS 로컬 단일 ACID 경계 — 반드시 원자적

```text
PRE-TRANSACTION (EOS / AE, bounded external calls)
  - Check trusted service identity and fresh OA authorization
  - Resolve immutable WC Decision / EOS approved proof with hashes
  - Read authenticated Artifact Manifest; build immutable evidence snapshot
  - Verify command, target company, candidate revision and tool trust

EOS POSTGRESQL TRANSACTION (one Unit of Work, no remote I/O)
  BEGIN
    1. Resolve/lock BusinessOperation and stable Idempotency Identity
    2. SELECT ... FOR UPDATE Candidate Revision + AccountingPeriod(company, period)
    3. Lock DocumentEnvelope consumption bucket; check amount and source uniqueness
    4. Verify approved immutable document hash, policy snapshot and accounting human proof
    5. Verify fresh OA evidence metadata; maker/checker separation and effective company scope
    6. Re-validate account active + leaf/postable + K-IFRS mapping + period OPEN + rule versions
    7. Validate balanced decimal debit/credit, currency, supported dimensions, evidence
    8. INSERT eos_accounting_approval_acceptance (exact revision hash + WC/OA proof)
    9. INSERT eos_journal_header + eos_journal_line (append only, POSTED)
   10. INSERT/UPDATE one-time approved-document consumption; Candidate state CAS to POSTED
   11. Write EOS BusinessOperation COMMITTED + Idempotency result + Outbox event
  COMMIT

POST-COMMIT
  - Outbox publisher delivers GL_POSTED to allocation/budget projectors
  - Verify journal by JournalId + source hash
  - Return actual POSTED journal_id. If ACK lost, query EOS by business_operation_id
```

**주의:** 위 순서는 논리적 설계이며 기존 `EosBusinessTransactionCoordinator`가 자체적으로 BusinessOperation/Idempotency/Outbox를 Transaction 안에 기록하는 구현을 재사용한다. 신규 Posting이 Coordinator 안에서 별도 Transaction을 열면 안 된다. 저장 순서/Lock/CAS의 DB 수준 상세는 SRS + PostgreSQL Acceptance에서 검증한다.

- **회계 승인과 Posting의 원자성 의미:** WC가 수락한 Human Decision 자체를 EOS 트랜잭션 안에서 기록하는 것은 불가능하다. 대신 EOS의 `ApprovalAcceptance` 기록과 GL PostedJournal Commit을 원자화한다. Cross-Service 인증·Outbox를 통해 end-to-end 업무 일관성을 갖춘다.
- **Concurrency:** `(tenant_id,company_id,candidate_id,candidate_revision)`에는 유일한 Posting 1건, 별도 `journal_id` UNIQUE. 제출/회수/문서 한도/기간마감의 동시성에 Lock + CAS + Unique 제약 적용.
- **Time-of-check/time-of-use:** OA의 마지막 권한증명을 짧은 유효시간과 해당 요청의 입력 Hash에 묶되 서비스 간 권한 철회가 반드시 Commit 전에 관찰된다고 보장할 수는 없다. 고위험 환경에서는 정책 Revision 재검증 Gate/운영 중지, 사후 감사/역분개 수단을 제공한다.
- **Fault:** Line insert 실패, 기간 상태 변경 경합, unique conflict, 승인 Proof mismatch 등 어떠한 실패도 `ApprovalAcceptance만 존재` 또는 `Journal Header만 존재`를 만들면 안 된다.

### 6.4 회계 분개·기간·역분개

- `eos_journal_line`은 `debit_amount`, `credit_amount`를 정확한 Decimal로 표현하며 두 필드 동시 양수 금지, 원단위/화폐 최소단위 정책 준수, 전표 통화별 `ΣDR=ΣCR`. 기존 v1 signed_amount를 폐기하지 않고 **v2 생성기에 sign 변환 계약**을 둔다.
- 원장 기표는 `eos_accounting_period`와 같은 EOS DB에서 행 잠금/상태 검사. `CLOSING/CLOSED` 기간 Posting 차단. 마감 결과와 GL의 동시성은 EOS DB에서 결판낸다.
- 역분개는 별도 승인된 정정 기안/전표를 대상으로 동일 회계 Human Gate/Posting ACID를 거친다. 이미 CLOSED 기간에는 승인된 개방 조정월로 전기 오류 수정 또는 소급 재작성 정책을 따르며 원전표 수정 금지.
- `GL JournalHeader/Line`이 유일한 정본; 계정잔액·시산표는 재구축 Projection. 마감 후 Journal 변경은 DB constraint/application immutability로 거부.

### 6.5 이벤트 타입과 재시도

새로운 versioned event types(예: `FINANCE.JOURNAL_POSTED.v1`, `FINANCE.JOURNAL_REVERSED.v1`, `FINANCE.ALLOCATION_RECONCILED.v1`)를 EOS 기존 Outbox schema와 Publisher에 추가한다. 현재 `EOS_EVENT_TYPES`에 신규 타입이 없으므로 registry/contract update 필요.

Consumer는 `(tenant_id,event_id)` dedupe, source journal revision/version check 및 watermark를 지킨다. Delivery는 중복 가능하지만 **계약상 결과는 한 번만 반영**된다. Consumer 장애를 GL Commit 장애로 오인하여 Posting을 재시도하지 않는다.

---

## 7. K-IFRS Account & Accounting Period Model (PAD-ADR-03)

**결정:** MyBee가 채택한 K-IFRS 기반 계정과목표를 회사 기준 초기 계정표로 채택한다. 다만 **K-IFRS 회계기준 그 자체가 회사별 사용할 상세 코드숫자 목록을 하나로 지정하는 것은 아니다.** 그러므로 설계서가 선택한 기준 계정코드·버전·출처를 검증하여 EOS catalog seed로 고정하며 임의 생성하지 않는다.

| 요구 | EOS To-Be |
|---|---|
| 기준 계정표 | Approved seed dataset + `catalog_release_id, source_ref, hash, effective_from` |
| 회사 적용 | `eos_company_account_policy(company_id, account_id, account_status, valid_from/until)` |
| 계정 계층 | Parent/Child 및 `postable_leaf` flag (상위 집계계정에 Posting 금지) |
| 재무제표 표시 | BS/PL classification and `statement_line_ref` version binding |
| 분개 규칙 | `posting_rule_release`, 유효기간, 승인된 Hash, 필요 시 조건별 Account Mapping |
| 계정 신설 `FL0004011` | 기안/승인 + 회계관리자 권한 + 코드 중복/계층/표시항목 검사 + 새 Release 게시. 기존 Posted 값은 변경하지 않음 |
| AccountingPeriod | `company + fiscal_year + period`, `OPEN/CLOSING/CLOSED`, version, close_by/proof. Posting 시 동시 마감 race 방지 |
| 회계 기준 판정 `FL0004005`, 규정 `FL0004006` | 승인된 K-IFRS RuleRelease와 사규/회계 규정 버전을 결정적 엔진에서 적용. LLM 계산/실시간 추론으로 Posting하지 않음 |

**주의:** 기존 `eos_account`의 tenant/account-code unique 조건과 account resolver를 유지한다. 다법인 계정 사용이 다르면 기존 PK를 강제로 변경하지 않고 회사별 policy binding으로 관리한다. `eos_account` 내부 관리자 Repository의 create 기능이 존재하더라도 회사별 승인된 계정 신설 REST/Skill은 별도로 보완해야 한다.

---

## 8. Project & Business Code Readiness (PAD-ADR-04)

MyBee의 강제 관리 업무코드 최소 5건은 다음과 같다.

| D12 Code | 의미 | Phase-1 EOS 의미 |
|---|---|---|
| `FL0012004` | 프로젝트 개설 | Project Business Request 승인 후 Creation |
| `FL0012005` | 업무 구성 확정 | `eos_project_work_code_set` 승인/버전 Lock |
| `FL0012006` | PM 지정 | 사람 PM vs PA Agent logical identity 구분 및 역할 승인 |
| `FL0012013` | 진행 보고 집계 | 정기 Reporting/진행 증적 필수 작업 |
| `FL0012026` | 프로젝트 종결 | 비용 미배부/미기표·미결재 항목 Closure Gate |

- EOS의 기존 `PROJECT.PROJECT.CREATE`는 Project+초기 OWNER를 생성하고 기술 상태 `ACTIVE`를 사용한다. 기존 Golden Project API를 바꾸지 않고 **v2 Business Readiness Overlay**를 추가한다.
- 신규 MyBee Project는 `DRAFT_CONFIGURATION → WORK_SET_APPROVED → MEMBER_READY → BUSINESS_READY` Gate를 통과해야 PA의 도메인 WRITE가 시작된다. 필수 5개 code 누락, 만료된 배정, PM 미지정, 법인 Binding 누락이면 `BUSINESS_READY=false`.
- D12 사용자·에이전트 배정은 Project membership과 별도 업무코드 수행권(`eos_project_work_assignment`)으로 관리한다. Member Role만 있다고 모든 업무코드 수행권이 생기는 것은 아니다.
- **계획 Man-Day 등급단가**는 공개 가능한 운영 기준과 **개인 실제 원가**를 구분한다. 급여·인건비 평가액을 PA/일반 PM에게 직접 노출하지 않는다.
- D04 예산 편성 `FL0004012`의 **금액 정본**을 EOS Budget에서 소유하고, D12 예산 배정 `FL0012008`은 Project-Budget Link만 가진다. 계획 수정은 immutable version, 실적은 POSTED GL와 Allocation에서 투영한다.

---

## 9. Project Allocation & Reconciliation (PAD-ADR-11/12/13)

### 9.1 회계 금액과 귀속 금액은 다른 진실

1. **POSTED GL**: 회계가 인식·기표한 회사의 자산/부채/수익/비용/자본 사실. `journal_header/line`이 정본.
2. **Allocation Ledger**: `eligible`한 Posted GL 수익·비용을 Project와 선택적 WorkCode로 분할한 관리 귀속 기록의 정본.
3. **Project P&L Projection**: Posted GL 직접귀속, 관리배부, 상시 업무 원가, 미배부/계획/미기표를 `as_of`와 워터마크를 포함해 제공하는 재생성 가능한 결과.

**Phase-1 `allocation_mode`:** `DIRECT` / `MANAGEMENT_ALLOCATION` / `GL_COST_TRANSFER` 중 한 원천 비용 성분에 단 하나. `MANAGEMENT_ALLOCATION`을 우선 채택한다. `GL_COST_TRANSFER`는 후속 옵션이며 해당 성분을 관리배부로 P&L에 다시 더하지 않는다.

### 9.2 SourcePool/Plan/Batch/Line

| 객체 | 불변 핵심 필드 | 정책 |
|---|---|---|
| `eos_cost_source_pool` | `tenant,company, source_journal_line_id, eligible_component_id, recognized_amount, eligible_amount, currency, source_kind, mode` | `POSTED`이고 회계적으로 적격한 원천만 생성. `(source_line, component)` unique. 세금/예수금/선급금/재고 미인식 성분은 비용 Pool 제외 |
| `eos_cost_allocation_plan` | `plan_id, revision, cost_kind, basis_kind, approved_rule_hash, approved_basis_source_ref, effective_period, approver_ref` | 계획 판/version/권한/근거 Lock |
| `eos_cost_allocation_batch` | `batch_id, period, source_set_hash, plan_revision, state, reconciliation_proof, operation_id` | 한번의 배부 실행, audit/idem/outbox |
| `eos_cost_allocation_line` | `pool_id, project_id, work_code?, cost_target, quantity/ratio, amount, basis_proof, rounding_delta` | Project별 귀속. 총액 검증, 개인 급여 노출 금지 |
| `eos_cost_allocation_adjustment` | `reversal_of, adjusted_amount, reason, approved_period, accounting_proof` | 변경 전 실적 Delete 없이 REVERSAL/ADJUSTMENT 기록 |

**배부 기준 우선순위 (MyBee 공용비용 근거):** 실적 원장 → 승인된 계획/업무 BOM → 사람·좌석·설비·라이선스 등 간접 연쇄 → 지정 비율(이유와 권한 필수). LLM의 임의 비율 생성은 승인된 계산 기준이 아니다.

**배부 정합성 (통화, Pool, 원천 비용 성분 기준):**

```text
E = eligible_posted_amount
D = recognized_direct_project_amount
A = sum(final management allocation amounts)
U = explicit unallocated/residual amount

For each source component: E = D + A + U
Constraint: D >= 0, A >= 0, U >= 0; sum(component E) <= eligible recognized GL amount
Exclusive: one component is DIRECT or MANAGEMENT_ALLOCATION or GL_COST_TRANSFER
If transfer mode: P&L applies transfer GL only; related management allocation is not double counted
```

음수 원천(환입/수익/취소)과 환율·차감 성분은 **signed basis**로 별도 같은 방향 보존식과 조정/역분개를 적용한다. `Decimal` 통화 최소단위로만 계산하고, 나머지는 **정해진 분배 우선순위 + `project_id` 안정 정렬**로 배정한다. 동일 source/plan/rule hash는 같은 배부 결과를 만든다.

**예산 실적:** `Budget Actual`은 POSTED GL + 확정 Allocation 투영에서만 계산. P&L에 `APPROVED_NOT_POSTED`, `FORECAST`, `RECONCILIATION_PENDING`은 **확정 실적과 분리**한다.

### 9.3 급여·구매 확장 시나리오

**급여(D08):** `FL0008021` 단가 산정, `FL0012044` 투입계획, `FL0008022` Project 배부, `FL0008013` 급여 전표 제안, `FL0004052` 집행 기록의 명령을 동일 원장 계약으로 연결한다. 급여는 그룹/법인 단위로 회계 전표를 Posting할 수 있다. 원가는 월 실적공수/계획/승인 비율로 Project 분할하되 개인 급여·예상단가·원가 역산이 가능한 세부 조회는 막는다. 회사부담 보험료/퇴직충당은 비용 성분에 반영하되 예수금/공제금은 **별도 추가 비용으로 이중 계상 금지**.

**구매(D15):** `FL0015009` 발주 생성, `FL0015010` 공용 품의·발주 승인, `FL0015017` 검수, `FL0015019` 매입 전표 제안. 한 승인된 발주에 여러 Project 라인을 담더라도 GL 원천은 회사 단위다. 매입한 자재 중 아직 사용하지 않은 재고/자산은 **즉시 Project 비용으로 인식하지 않는다**. 재고 소비·불용 처리 등 회계적으로 적격한 비용 인식 사실을 SourcePool로 만든다.

### 9.4 P&L API 투영 계약

| 출력 열 | 의미 | 확정 여부 |
|---|---|---|
| `posted_revenue` | 실현/인식 수익 원장의 수익귀속 | 확정 (POSTED) |
| `posted_direct_cost` | Project 직접귀속된 회계 적격 원가 | 확정 (POSTED) |
| `posted_allocated_cost` | GL Source Pool에서 보존식 검증 완료된 관리원가 | 관리손익 확정 (회계 GL 투영) |
| `operating_or_unallocated_cost` | 미배정 잔액·공통 운영원가 | 별도 상태, Project에 임의 분산 금지 |
| `approved_not_posted` | 업무/회계 승인만 진행/완료, GL 미기표 | **확정 손익 제외** |
| `planned_budget`, `forecast` | 편성 예산/예측 | 확정 손익 제외 |
| `as_of, posting_watermark, allocation_watermark, reconciliation_status` | 데이터 기준 시각/신선도/정합성 | 필수 메타데이터 |

**P&L 직접귀속/배부 중복방지:** 원천 GL 비용 라인은 Project 직접귀속/공용배부/미배부 중 **하나**의 분기로 계산한다. 회계비용 계정의 모든 Dr 합과 Project 비용의 합을 단순 합산해서는 안 된다. NVT/상위 Project Roll-up은 자식 Project 실적을 정확히 한 번만 합산한다.

**급여 비밀유지:** `OA Project Scope`뿐 아니라 `data_classification`, 집계 인원/소규모 셀, 집계 결과의 차분 공격을 고려한 조회 제한을 적용한다. PA/PM에게 개인 실제 원가·임직원 급여 구성 요소를 노출하지 않는다. 등급별 계획 MD 단가와 실제 내부 원가를 다른 Projection으로 둔다.

---

## 10. Canonical Business API / NSL Tool Contract (PAD-ADR-14)

### 10.1 원칙

- `FL0004008` 등의 MyBee 업무코드는 **업무 ID**이고, NSL Tool ID·EOS REST API ID와 반드시 1:1 대응하지 않는다.
- Canonical Tool Contract는 Provider 독립적이며 AE Runtime Binding이 EOS API에 연결한다. NSL v0.2 Compiler/Runtime/Core Approval/Idempotency 코드는 변경하지 않는다.
- 회계승인은 사람의 OA 유효 권한·WC WorkItem 결정이다. 새로운 NSL Skill이 회계승인 판단을 스스로 `APPROVE`해서는 안 된다.
- **단일 NSL WRITE**의 BusinessOperation + EOS idempotency + EOS Posting/Allocation Verification이 일치해야 한다. 여러 업무 단계는 WC가 orchestration한다.
- 기존 EOS `FINANCE.CREATE_VOUCHER_DRAFT` v1, AE command builder, Golden A examples, DB CHECK 및 테스트는 유지한다. 신규 계약은 버전/operation을 추가하며 구버전 의미 변경 금지.

### 10.2 신규/확장 Contract 후보(최종 식별자·스키마는 SRS 확정)

| Canonical Operation 후보 | Capability | EOS SoR/주요 검증 | 변경 |
|---|---|---|---|
| `BUSINESS.DOCUMENT_APPROVED.GET` | READ | Immutable approval document envelope, proof/hash/allowance | NEW |
| `PROJECT.WORK_CODE_SET.GET/APPROVE` | READ/WRITE | Mandatory 5-code/version/BusinessReady | NEW |
| `FINANCE.ACCOUNT.CATALOG_GET` | READ | K-IFRS catalog/policy/effective leaf | ADD |
| `FINANCE.ACCOUNT.CREATE_APPROVED` | WRITE | FL0004011 인간 승인 + 새 Release | NEW |
| `FINANCE.VOUCHER_CANDIDATE.CREATE_V2` | WRITE | Approved document proof required; company scope; expected revision | NEW |
| `FINANCE.VOUCHER_CANDIDATE.VALIDATE` | READ | K-IFRS/Period/Balance/attachments/source classification | NEW |
| `FINANCE.ACCOUNTING_APPROVAL.REQUEST` | WRITE | WC human task creation (not accountant approval itself) | NEW |
| `FINANCE.VOUCHER.APPROVE_AND_POST` | WRITE (critical) | EOS short ACID after actual Human Decision Proof | NEW |
| `FINANCE.JOURNAL.GET/VERIFY/RECONCILE` | READ | committed journal/operation/outbox/reference, no duplicate retry | NEW |
| `FINANCE.JOURNAL.REVERSE` | WRITE (critical) | new correction approval + immutable reverse | NEW |
| `FINANCE.COST_ALLOCATION.RUN` | WRITE | GL POSTED SourcePool + approved Plan + no double count | NEW |
| `FINANCE.COST_ALLOCATION.VERIFY` | READ | pool conservation, version, reconciliation | NEW |
| `FINANCE.PROJECT_PNL.GET` | READ / role filtered | Project/NVT P&L actual vs pending vs plan + watermarks | NEW |

**REST endpoints는 EOS 내부 namespace로 한정하고, 기존 `contracts/openapi/nex-eos.openapi.yaml`에 additive route로 등록**한다. 기존 도메인 문자열/Scope/데이터 구조와 충돌할 때 이름부터 임의 확정하지 않고 Registry 점검 Gate를 둔다.

### 10.3 현재 소스의 1차 차단 Gate

`AE nsl_eos_write_execution.py::build_eos_create_voucher_command()`는 기존 v1에서 `business_approval_proof_ref=None`을 출력한다. MyBee 새 v2 경로는 **이 v1 builder 결과로 Posting할 수 없음**을 계약으로 고정한다. `proof_ref`가 non-null로 채워졌다는 사실만 확인해서도 안 된다. EOS는 Proof SoR·Hash·회사·금액·정확한 문서 Revision·정책·사용잔액을 실제로 검사해야 한다.

---

## 11. Scope / Phase-1 Minimum Vertical Slice

### 11.1 포함

1. EOS Company/Legal Entity, Project 법인 Binding 및 최소 K-IFRS 기반 계정표·계정/기간 정책.
2. D12 Project 생성 및 필수 Work Code Set, PM/Member 및 BusinessReady.
3. D04 기안·품의 승인 Proof 필수 + `VoucherCandidate` v2 생성/검토.
4. 회사/복수 Project 공용전표에 대한 Human Accounting Approval Case.
5. EOS Atomic GL Posting, 승인 증명 Usage, Journal 조회/역분개, 실패·재시도 대사.
6. POSTED GL line 기반 Project Allocation + 원가 보존/반올림/Adjustment.
7. EOS Budget SoR와 Project 연결, P&L READ, NVT rollup, 승인 전/후 수치 분리, Privacy.
8. Golden A/P8/NSL 기존 회귀 및 신규 E2E·PostgreSQL Fault Test.

### 11.2 다음 차수 또는 별도 Domain Slice

- 급여 계산 엔진 전체, 원천징수·보험공단 정산 전체, 상세 세무·신고, 모든 자산 감가상각 규칙, 연결 재무제표·공시/XBRL, 구매 MRP/MPS/BOM 전체 자동화.
- 단, 공용 급여 합계 및 구매 검수/재고와 Project 손익의 연결은 Phase-1 **최소 Demo/실증 시나리오**로 추가할 수 있도록 공통 Contract를 먼저 확정한다.
- `GL_COST_TRANSFER`의 완전 자동화는 Phase-1 기본 구현 제외(비중복 정책만 고정).

### 11.3 구현 Slice Sequence — PAD 확정 순서, 상세 SRS 이후 코딩

| Slice | 내용 | 최소 Acceptance |
|---|---|---|
| `S0` | Frozen/Golden A Baseline & Contract Evidence | Frozen 변경 0, Golden A 기존 시나리오 기준선 기록 |
| `S1` | Legal Entity, Account Catalog/Period, Project Work Code Ready | K-IFRS seed 출처, 기간 OPEN, 5개 Work Code Gate |
| `S2` | Approved Document Envelope + Company Scoped Approval Subject v2 | Ref missing/wrong company/invalid revision → fail closed |
| `S3` | MyBee VoucherCandidate v2 + Rule/Balance Validation | v1 untouched, amount/revision immutability |
| `S4` | Accountant Human Review + EOS Proof Acceptance/Atomic Posting | 회계 승인 없는 POSTED 0; 같은 입력 Posting 1회; PostgreSQL rollback PASS |
| `S5` | Reverse/Period/GL Query/Operation Reconciliation | closed period/race/UNKNOWN 복구 PASS |
| `S6` | SourcePool + AllocationPlan/Batch/Line + Conservation | 1/N 공용배부, 0원 차이, 재고 선인식 0 |
| `S7` | D04 Budget SoR / D12 Link + P&L Projection/Privacy | NVT roll-up/수익 비용 구분/시점 watermark/PA 급여 차단 |
| `S8` | NSL v2 Tool Binding + Domain Pilot (급여/구매) | E2E, v1 Golden A, OA/WC/NSL 회귀 PASS |

**병렬 가능 구간:** `S1` 안에서도 Project Ready와 Account+Period DB는 소유 Aggregate가 분리되어 병렬 작업 가능. 단 `S4` 승인과 Posting은 동일 통합 테스트 완료 전 PROD 활성화 금지.

---

## 12. Acceptance / Negative / Fault Gates

| Gate | 검증대상 | 반드시 실패/성공 확인할 시나리오 |
|---|---|---|
| **G-A Frozen Contract** | P8/Golden A/NSL v0.2 | 기존 v1 Draft payload, tool IDs, migration/schema, examples 회귀 PASS; Frozen file 변경 0 |
| **G-B Proof Binding** | 기안서 승인 | 미승인/취소/만료 문서·다른 회사·Revision/hash 불일치·첨부 교체·한도 초과·이중 사용 → Candidate 생성 및 Posting 차단 |
| **G-C Human SoD** | Accountant approval | 승인권 scope 없는 사람, 본인 기안/작성 전표 승인, 회계 조직 범위 미일치, 철회된 권한 → POSTED 0 |
| **G-D Posting ACID** | 실 PostgreSQL | Journal line #3 insert crash, ProofAcceptance insert crash, Outbox fail, 동시 Posting 20회, 기간마감 경합 → half-commit 0, duplicate journal 0 |
| **G-E Failure Recovery** | ack loss/Timeout | POSTED 뒤 통신 실패, 동일 idem replay, payload conflict, Approval event 중복·순서 역전 → original journal retrieval / 409 / reconcile |
| **G-F Accounting Master** | Account/Period/Rules | account invalid/parent/non-postable, closed period, stale rule, ΣDr≠ΣCr, mixed currency → fail-closed |
| **G-G Allocation** | Pool/Plan/Line | Source POSTED 아님, 1:N 반올림 잔차, 동일 GL line 중복 Pool, 취소·조정, GL_TRANSFER 중복 → conserved sums / no double count |
| **G-H P&L & Privacy** | Project/NVT/Payroll | 미기표 포함 금지, 상위집계 2회 합산 금지, 소인원 인건비 추론 차단, 다른 법인/tenant 데이터 노출 차단 |
| **G-I Project Gate** | D12 5개 업무코드 | 5개 빠지거나 PM·Member·법인 누락 → 신규 MyBee BusinessReady 불가. 기존 P8 Project API 호환 유지 |
| **G-J Original PDF** | D04 v1.9 / D12 v2.8 | PDF 조항/도식/업무코드/회계승인·Posting 정의 페이지별 대조; 충돌사항 Change Ledger 기록 및 Resolution |

**관계 테스트:** `ApprovalProof → CandidateRevision → PostingAcceptance → JournalLine → CostPool → AllocationLine → ProjectPnlProjection`의 역추적 가능성을 테스트하고 각각 ID/Hash/결재 정책 버전을 조회할 수 있어야 한다.

**실행 완료를 의미하지 않는다:** 본 PAD는 통합 테스트를 실행하지 않았다. SRS/실구현에서 PostgreSQL smoke, pytest, 계약 회귀, 보안/개인정보 검증 Gate를 통과해야 Production 적용 가능.

---

## 13. Decision→Gap Traceability Matrix

| Audit Gap | PAD 확정 결정 | SRS/구현 위치 |
|---|---|---|
| G01 v1 proof optional / None | ADR-05,06,14 | `ApprovedDocumentEnvelope`, `VoucherCandidate.CREATE_V2` |
| G02 only DRAFT | ADR-06,09 | `eos_voucher_candidate`, immutable revisions |
| G03 Accounting Human Gate 없음 | ADR-07,08 | Company Scoped Case, OA SoD, WC Approval |
| G04 GL Posting 없음 | ADR-09,10 | Journal, PostingAcceptance, UoW |
| G05 AccountingPeriod 없음 | ADR-03,09 | AccountingPeriod lock, close/post race |
| G06 Allocation/P&L 없음 | ADR-11~13 | Pool/Batch/Line, Project P&L |
| G07 K-IFRS seed/leaf 부족 | ADR-03 | CatalogRelease + CompanyAccountPolicy |
| G08 Company scope vs project_id NOT NULL | ADR-02,07 | Legal Entity + ScopedApprovalCase v2; no fake project |
| G09 Project 5-code/Ready 없음 | ADR-04 | WorkCodeSet, BusinessReady Overlay |
| G10 Grade/MD assignment 없음 | ADR-04,13 | WorkAssignment + plan/actual privacy |
| G11 Budget SoR 없음 | ADR-13 | Budget, ProjectBudgetBinding |
| G12 AE NSL Draft-only | ADR-14 | versioned Tool+AE Binding |
| G13 event type 부족 | ADR-09,15 | EOS Outbox event contract |
| G14 Shared voucher project_id 강제 | ADR-02,06,11 | company-scoped Candidate + allocation |
| G15 Payroll reverse inference | ADR-13 | privacy-aware P&L/small-cell query guard |
| G16 Project close only DEACTIVATE | ADR-04 | business Close Gate separate from status |
| G17 Fault tests missing | ADR-09~15 | PostgreSQL fault/race + E2E test gates |
| G18 PDF 상세 대조 미완료 | Source Gate | `G-J`, Change Ledger entry |

---

## 14. Open Verification Issues & Change Control

| ID | 항목 | PAD 판단 | Closure 조건 |
|---|---|---|---|
| `OV-01` | D04/D12 PDF 전문 대조 | **설계 보류 아님, 원문 Gate 미완료** | PDF 페이지별 발췌로 기안/회계승인/업무코드/원장 용어 불일치 확인 및 처리 |
| `OV-02` | MyBee 채택 K-IFRS 상세 계정표 seed | **목록 임의 생성 금지** | 실제 기준 계정코드/버전/source hash/계층·재무제표 매핑 확보 |
| `OV-03` | Company Scoped ApprovalCase v2 schema | 범위·책임 결정 완료 | WC/OA/EOS Contract/Race/SoD/Proof Hash 검증 |
| `OV-04` | 신규 BusinessOperation/Tool Registry 이름 | 논리 ID 제안 | 기존 Registry 충돌 확인, 최종 JSON Schema / OpenAPI Freeze |
| `OV-05` | 회계 처리 다법인·다통화 | 법인/통화 차원 의무화 | 회사별 정책과 Phase-1 지원 통화 범위 결정 |
| `OV-06` | `Near Real-time` P&L | Watermark/Status 의무화 | 운영 지연 목표/재시도/배치 처리 SLO 수치 정의 |
| `OV-07` | 배부 인정의 법정회계 적합성 | 관리배부 우선 | 회계책임자 승인 정책, 재고/급여 회계 인식 원칙 검증 |
| `OV-08` | 권한 철회 직후 Posting race | Fresh OA Evidence + short local UoW | 현재 OA revision/TTL/대사·재인증 실DB/회귀 테스트 |
| `OV-09` | Architecture amendment 필요 여부 | **현재 PAD는 Frozen 의미 변경 없이 설계** | 실제 구현 중 Frozen 변경 요구 발생 시 Controlled Amendment만 허용 |

---

## 15. Next Deliverables — 명시적 Handoff

이 PAD에서 **일관되게 정해진 설계 원칙**을 기준으로 다음 작업을 수행한다.

1. **`NeX–MyBee D04/D12 EOS SRS v1.0`**: Aggregate별 schema, Command/Query/State/Error, OA Scope, Business Approval Proof v2, Posting Lock/CAS, Allocation conservation·privacy NFR, 시나리오·Acceptance 수치 확정.
2. **`NeX–MyBee D04/D12 EOS Implementation Slice Plan v1.0`**: S0~S8을 Codex 작업 단위(파일/마이그레이션/계약/pytest/Postgres smoke/Gate/Commit)로 분할.
3. **`D04/D12 MyBee PDF-to-PAD Trace Verification`**: D04 v1.9 / D12 v2.8의 페이지별 조항을 `PAD-ADR-01~15`와 대조하고 충돌 항목이 있으면 Change Ledger에 기록. Freeze 이후에는 별도 변경심의.

**완료 판정:** 이 문서는 **Architecture Decision Baseline 수립 완료**. Production 구현/원문 정합성/테스트까지 완료되었다는 의미가 아니며, 구현 이후 반드시 `Gate A~J` 통과 필요.

---

## Appendix A. Source References (read-only, pinned revision)

### A.1 NeX Platform

- [Frozen Architecture Consistency Closure v1.0](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/docs/frozen/v2.1/10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md)
- [EOS BusinessTransaction/Idempotency/Outbox](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/services/nex-eos/nex_eos/business_transactions.py)
- [EOS Account model](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/database/nex-eos/migrations/2505_eos_account.sql)
- [EOS VoucherDraft model](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/database/nex-eos/migrations/2506_eos_voucher_draft.sql)
- [EOS ApprovalInstance schema](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/database/nex-eos/migrations/2510_eos_approval_instance.sql)
- [EOS Immutable ApprovalProof schema](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/database/nex-eos/migrations/2511_eos_approval_proof.sql)
- [AE Voucher Draft v1 command adapter (approval proof=None)](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py#L471-L523)
- [EOS voucher command implementation](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/services/nex-eos/nex_eos/voucher_commands.py)
- [EOS project aggregate](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/services/nex-eos/nex_eos/projects.py)
- [EOS project member aggregate](https://github.com/nurigitdev/2607_nex_platform/blob/c2c03b20e22691cc1984f044e0cacd5d698f9bd3/services/nex-eos/nex_eos/project_memberships.py)

### A.2 NSL v0.2

- [NSL Tool Contract Detailed Design](https://github.com/nurigitdev/2608_nsl/blob/f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4/docs/v0_2/06_NeX_Skill_Tool_Contract_Detailed_Design_v0.2.md)
- [VoucherDraft NSL WRITE Skill example](https://github.com/nurigitdev/2608_nsl/blob/f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4/examples/voucher_draft_validation/voucher_draft_write.ns)

### A.3 MyBee (HTML 검증, PDF는 파일 목록 확인)

- [MyBee 프로젝트 인건비 예산·집행 v1.7](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8%EC%9D%B8%EA%B1%B4%EB%B9%84%EC%98%88%EC%82%B0%EC%A7%91%ED%96%89_%EC%84%A4%EA%B3%84%EC%84%9C_v1.7.html)
- [MyBee 공용비용 통합결재 v1.1](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%EA%B3%B5%EC%9A%A9%EB%B9%84%EC%9A%A9_%ED%86%B5%ED%95%A9%EA%B2%B0%EC%9E%AC_%EC%84%A4%EA%B3%84%EC%9A%94%EC%95%BD_v1.1.html)
- [MyBee 프로젝트 생성 신청 자료·UI v1.12](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8%EC%83%9D%EC%84%B1%EC%8B%A0%EC%B2%AD_%EC%9E%90%EB%A3%8C%C2%B7UI%EC%84%A4%EA%B3%84%EC%84%9C_v1.12.html)
- [D04 회계 PDF — 파일 존재 확인](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%EC%97%85%EB%AC%B4%EC%8A%A4%ED%82%AC%EC%84%A4%EA%B3%84%EC%84%9C_D04_%ED%9A%8C%EA%B3%84%EC%97%85%EB%AC%B4_v1.9.pdf)
- [D12 프로젝트수행 PDF — 파일 존재 확인](https://github.com/nurigitdev/2611_MyBee_Blueprint/blob/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin/MyBee_%EC%97%85%EB%AC%B4%EC%8A%A4%ED%82%AC%EC%84%A4%EA%B3%84%EC%84%9C_D12_%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8%EC%88%98%ED%96%89%EC%97%85%EB%AC%B4_v2.8.pdf)

---

## Appendix B. Document Integration & File Consistency

- Source Audit: `NeX_MyBee_D04_D12_EOS_Source_Audit_and_Gap_Analysis_v1.0.md` — source-based G01~G18.
- Contract Closure: `NeX_MyBee_D04_D12_Accounting_Transaction_Contract_Closure_v1.0_RC1.md` — C1~C6.
- PAD: **이 문서** — PAD-ADR-01~15, Ownership Boundary, Implementation Exit Gates.
- Next SRS: source/decisions을 그대로 추적하도록 `REQ-D04-*`, `REQ-D12-*`, `REQ-GL-*`, `REQ-ALLOC-*`, `REQ-PNL-*` ID 체계를 사용한다.
