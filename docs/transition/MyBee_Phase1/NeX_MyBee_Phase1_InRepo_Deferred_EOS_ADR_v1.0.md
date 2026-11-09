# NeX–MyBee Phase-1 In-Repository Development & Deferred EOS Extraction — Architecture Decision v1.0

**Document ID:** `NEX-MYBEE-P1-INREPO-DEFER-EOS-ADR-20261109-V1.0`  
**Date:** 2026-11-09 (Asia/Seoul)  
**Status:** `ACCEPTED — PHASE-1 DIRECTION / IMPLEMENTATION PENDING`  
**Decision sponsor:** NeX–MyBee Phase-1 개발 책임자의 대화상 설계 방향 승인. GitHub 커밋·PR 승인이나 조직의 정식 변경관리 완료를 의미하지 않음.  
**Baseline repository:** `nurigitdev/2607_nex_platform`, `master`  
**Decision scope:** Phase-1 동안 EOS 물리적 Repository 분리를 유예하고, 기존 NeX 모노레포 내부의 EOS 독립 서비스에서 Project Agent·회계·Project P&L을 구현한다.  
**Normative priority:** NeX Platform v2.1 Frozen / Agent v2.1 / 인정된 NSL v0.2.x 계약 → D04/D12 EOS Contract Closure · PAD · SRS → **본 ADR(Phase-1 Repository/Execution 전략에 한정)** → 기존 Repo Boundary PAD 및 ISP v1.1의 Repository 실행 계획.  
**Change class:** `Repository/Delivery Strategy Amendment ONLY`; EOS Business Transaction SoR, WC/OA/AE/WA/NSL 및 회계 Aggregate의 계약과 책임은 변경하지 않는다.  
**Implementation claim:** 이 문서 작성은 설계·검증 작업이며 기능 구현, DB Migration, PostgreSQL Acceptance, Git Branch/PR/Merge 또는 배포를 수행한 것이 아니다.

---

## 0. Decision in one page

> **DECISION:** MyBee Phase-1의 `Project Agent → 업무 승인 → 전표/회계 승인 → EOS Atomic GL Posting → Project Allocation → P&L`을 기존 `2607_nex_platform` 모노레포에서 신속하게 구현한다. 기존 `nex-eos` 서비스와 EOS DB를 그대로 사용하고, EOS의 별도 Repository 추출은 **Phase-1 Acceptance 이후** 측정된 비용·가치를 근거로 다시 결정한다. MyBee의 도메인 코드는 지금부터 별도의 패키지·계약 경계를 유지하지만 **별도 저장소 생성은 Phase-1 필수 선행조건이 아니다**.

### 0.1 확정 지시

1. **NeX Platform `master` 유지.** 기존 Short-lived Feature Branch → PR → Gate → Merge 운영을 계속한다. `feature/mybee-phase1` 장기 브랜치, 영구 통합 브랜치는 만들지 않는다.
2. **EOS 구현 유지.** `services/nex-eos/nex_eos/`, `database/nex-eos/migrations/`, `contracts/openapi/nex-eos.openapi.yaml` 및 현행 EOS DB 소유권을 이동·복제하지 않는다.
3. **MyBee Domain은 모노레포 내부에서 논리적으로 분리.** 업무코드/Skill Pack/기안서 템플릿/급여·구매 소스 어댑터가 `nex_eos` Business SoR 및 DB를 소유하지 않도록 한다.
4. **Frozen Architecture 불변.** EOS Business Transaction SoR, WC Human Work/Approval, OA Authorization, AE Agent/NSL Integration, WA Evidence; 기존 v1 Golden A/NSL Tool 계약은 보호한다.
5. **최우선 결과는 동작하는 E2E.** 시험 데이터 기반 Project Agent + Accounting/GL + Project Allocation + Project P&L을 조기 통합하고, 외화/매매기준율·회계 기간·승인/보안·대사까지 포함하는 Phase-1 Closure Gate를 유지한다.
6. **분리는 시기만 유예하며 가능성은 보존.** 외부 API·소유 DB·내부 모듈 경계·독립 테스트가 지켜져야 한다. `EOS Core/Full`은 별도 Fork가 아니라 **동일 코드베이스의 배포 프로파일 후보**이며 현재 구현되어 있는 스위치라고 주장하지 않는다.
7. **기존 구현 계획의 기능 범위를 취소하지 않는다.** D04/D12 SRS 116개, v1.0/v1.1의 37개 S0~S8 작업, PostgreSQL fault 18건, E2E 12건 유지. 이전 Repo 분리/Two-PR 필수 규정만 Phase-1에 한해 재기준화한다.

### 0.2 Change control의 정확한 범위

- **변경되는 것:** Phase-1 소스 배치 위치, Git Repository 대상, 선행 PR·CI 토폴로지, MyBee 전용 부가 작업의 착수 순서, EOS Repository 추출의 시점.
- **변경되지 않는 것:** EOS에 귀속되는 직원·조직·Project·Business Approval·Account·VoucherCandidate·GL·FX·Allocation·Budget·P&L의 SoR 책임 및 데이터 계약; MyBee에서만 수행하는 인사·급여·총무·자금관리·구매 도메인 정책; OA와 WC의 독립 책임.
- **절대 자동 변경하지 않는 것:** NSL 문법/컴파일러/WRITE OperationKind, P8/Golden A v1 `CREATE_VOUCHER_DRAFT` 의미, 기존 Migration 내용, 결정적 Posting 원자성, 승인 Proof의 유효성·SoD, 게시된 GL 불변성.
- **별도 Controlled Amendment 필요:** Frozen Service SoR를 다른 서비스로 이동, WC/OA의 결정권 교체, 승인·Idempotency·Commit State 계약의 본질적 변경, NSL `POST` OperationKind 신설, DB 경계 위반.

---

## 1. Decision drivers and baseline evidence

### 1.1 왜 지금 분리보다 구현 경험이 중요한가

- NeX v2.1 Agent Runtime과 NSL은 이미 EOS에서 실제 Voucher Draft를 생성·검증하는 흐름을 갖고 있다. 분리를 먼저 추진하면 고위험 인증/승인/트랜잭션 경계를 먼저 재구축해야 한다.
- Project Agent가 기업 조직·Project·PM/Member·업무코드를 통해 업무를 받아 결과를 내고, 실제 회계 원장과 손익에 귀속시키는 **첫 업무 Vertical Slice**를 빨리 검증하는 것이 핵심 학습 목표다.
- 제품/배포 분리의 경제성은 Phase-1에서 관측할 실제 의존성, 커밋 변동률, 서비스/DB 경합, 출시 주기, 외부 재사용 요구를 근거로 판단하는 편이 정확하다.
- 모노레포라도 `nex-eos`는 이미 독립 서비스와 전용 DB Migration, EOS OpenAPI를 갖고 있어 모듈/데이터 경계를 유지할 수 있다.

### 1.2 검증한 소스/문서 기준선

| 근거 | 관찰된 정보 | 본 결정에 미치는 영향 |
|---|---|---|
| [NeX Platform](https://github.com/nurigitdev/2607_nex_platform) | `master@5e64fb1f6b9af2198797d1bcdbc82e577b098fbe`, 2026-11-09 UTC 04:29 커밋 확인 | Phase-1 구현 기준점. Codex 착수 시 HEAD 재확인 |
| `services/nex-eos/nex_eos/` | EOS Python source modules 38개, `app.py`에서 Project/Org/Account/Voucher/Approval API 등록 | 서비스 수준 독립성 확보, Repo 즉시 추출 불필요 |
| `database/nex-eos/migrations/` | 16개 SQL Migration `2500`~`2515` 존재 | 신규 D04/D12 Migration 2516+ 후보, 실제 작성 직전 충돌 검증 |
| `contracts/openapi/nex-eos.openapi.yaml` | EOS Canonical API 계약 존재 | MyBee 업무로직이 EOS 소스/DB가 아닌 API를 호출할 수 있는 경계 |
| `docs/development_process.md` | Slice / Checkpoint / Full Gate 및 Golden Journey Runner 기준 | 기존 CI 질서 재사용; 실제 Gate 실행 결과는 아직 없음 |
| `services/nex-eos/nex_eos/dependencies.py` | EOS 런타임이 OA/WC, 공통 `nex_runtime`과 명시적으로 연계 | 분리 시 의존성/배포 영향이 커서 Phase-1에 전제하지 않음 |
| [NSL](https://github.com/nurigitdev/2608_nsl) | `master@f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4` | 별도 코드베이스 및 인정된 Wheel 고정. 신규 언어 변경 불필요 |
| [MyBee Blueprint](https://github.com/nurigitdev/2611_MyBee_Blueprint) | `main@948b50fd43fc4e0f0d3f40ffd6335871ec741559`, 접근 재확인 | D04/D12 기준자료; 실행 코드가 아님. PDF 페이지별 원문 대조는 미완료 |
| Existing D04/D12 artifacts | Contract Closure, Source Audit, EOS PAD v1.0, SRS v1.0, ISP v1.0/v1.1, Repository Governance PAD v1.0 | **기능/회계 설계 재작성 없이** Repository 실행 전략만 수정 |

**Evidence limitation:** 저장소 목록·파일 구조를 읽어 확인한 것이며 테스트 통과/Production 호환성 인증은 아님. 원본 D04/D12 PDF는 GitHub에 존재하지만 페이지별 내용 검토는 별도 Gate다. 날짜·커밋은 문서 작성 시점의 관측값이다.

### 1.3 기존 실제 EOS 경계

```text
NeX Platform Monorepo (git: master)
├─ services/nex-ae-api/        AE/IA/PA, NSL execution/verification
├─ services/nex-oa/            Authentication / PDP / principal
├─ services/nex-wc/            Work routing / human approval workflow
├─ services/nex-wa/            Artifact/Evidence
├─ services/nex-eos/           Business Transaction / formal approval / Project / GL (to extend)
├─ database/nex-eos/           EOS DB-owned migrations
├─ contracts/openapi/          Provider-owned canonical API
├─ apps/nex-ae-web/            Existing AE presentation
└─ tests/                      Existing Golden A / EOS integration regressions

Separate source repos (not required to merge into platform):
  2608_nsl                immutable/admitted NSL releases
  2611_MyBee_Blueprint    reference designs; not business runtime
```

---

## 2. Alternatives — decision log

| Option | Decision | Strengths | Weakness / reason |
|---|---|---|---|
| A. EOS를 즉시 별도 Repository로 추출하고 MyBee 분리 | **DEFER** | 구조·배포 독립성 조기 확보 | PA/Golden A/Auth/DB/CI를 동시에 재구축해야 하므로 Phase-1 검증 목표 지연 및 회귀 위험 |
| B. EOS Lite를 NeX에 두고 EOS Full을 MyBee에 복사·포크 | **REJECT** | 단기 코드 재사용 쉬움 | 두 SoR/두 승인·전표 의미, 보안 수정 누락·Migration Divergence·회계 대사 위험 |
| C. MyBee를 NeX 장기 개발 브랜치로 운영 | **REJECT** | 초기 분기 단순 | 거대 Diff, 잦은 Merge Conflict, Golden A 퇴행, 병합 목적 불명확 |
| D. 기존 모노레포에서 EOS 독립 서비스·MyBee Domain 패키지 경계를 지키며 Phase-1 구현 | **SELECT** | 기존 Runtime/CI/Test/DB 직접 재사용, 빠른 E2E, 필요시 추출 가능 | 모노레포 배포·팀 소유 경계가 약해질 수 있어 강제 Code/Contract Gate가 필요 |
| E. 현재 EOS만 구현하고 MyBee Domain은 Phase-1 이후 | **PARTIAL / NOT SUFFICIENT** | GL 기반을 빨리 완성 | 실제 PA→업무코드→기안→원가 흐름을 검증하기 어려움; 최소 MyBee 도메인 통합은 반드시 포함 |

**Selected variant:** `D`, 기존 제품 논리 경계 유지 + Phase-1 Monorepo 동시 개발. `A`는 Phase-1 종료 후 객관적 검토, `B/C`는 금지.

---

## 3. Formal architecture decisions

### ADR-P1-01 — Runtime topology / repository

**Decision:** Phase-1 동안 `nurigitdev/2607_nex_platform` 단일 구현 저장소에서 AE/PA/EOS 및 최소 MyBee Integration을 개발한다. NSL과 Blueprint는 각기 기존 저장소를 유지한다. 새 `2611_MyBee_Service`나 `2611_nex_eos` Repo는 Phase-1 선행조건이 아니다.

**Guard:** 각 기능은 기존 Service SoR에 귀속되고, MyBee 전용 파일을 Platform의 `_shared`/EOS 내부로 무분별하게 이동하지 않는다. Phase-1 Repository 단일화는 업무 SoR 통합을 의미하지 않는다.

### ADR-P1-02 — EOS logical/physical ownership

**Decision:** `nex-eos`는 동일 NeX 모노레포 내부의 독립 Backend Service로 유지하며 자기 DB/Migration/Transaction을 소유한다. Canonical Business API는 EOS가 제공하고 MyBee는 호출한다.

**Guard:** 하나의 실행 환경·법인 장부에 하나의 권위 있는 EOS SoR만 둔다. Dev/Test/Prod 물리 DB는 분리될 수 있어도 양쪽에 별도의 회계 SoR가 생기면 안 된다. Cross-service SQL JOIN/FK와 MyBee의 EOS DB Connection을 금지한다.

### ADR-P1-03 — Enterprise OS의 공통 Core Domain

**Decision:** Employee(기본 직원 레퍼런스), Organization, Project/NVT, Member, BusinessFormalApproval, ApprovedDocument, VoucherCandidate, AccountingApproval, Account, FX/Period, PostedJournal/GL, Allocation, Budget, Project/NVT P&L은 EOS-owned domain이다.

**Boundary:** OA는 인증·Principal·RoleBinding·조직/Project Authorization PDP를 최종 판정; WC는 인간 결재 작업의 routing/claim/decision; EOS는 조직·직원 업무 Master와 Business Approval/Transaction SoR. EOS가 OA와 WC를 중복 구현하지 않는다. Employee/Organization Master의 새 API·데이터 범위는 SRS와 OA 관계를 검증한 뒤 additive하게 도입한다.

### ADR-P1-04 — MyBee Domain ownership, no fork

**Decision:** MyBee(사무 AX)는 업무코드 카탈로그/버전, 기안서·증적 Template, Skill Pack 및 FL→NSL Tool 매핑, 급여 계산 소스, 인사·총무·자금관리·구매 업무정책, Domain UX를 소유한다. Phase-1 최소 구현은 모노레포 내 분리된 디렉터리/패키지로 만든다.

**Guard:** MyBee가 EOS `Journal`, `ApprovalProof`, `ProjectPnl` 정본을 보유하거나 EOS migrations를 복사해 자체 적용해서는 안 된다. 매입/급여 발생 원가는 인증된 Business API/Approval을 통해 EOS로 전달된다. MyBee의 예측·신청 자료는 관리용 Draft/Source Evidence로 표시한다.

### ADR-P1-05 — Canonical data & command boundary

**Decision:** MyBee Domain은 EOS·OA·WC의 공식 API/Tool을 이용한다. 같은 Git Repository에 있다고 `from nex_eos...` 내부 저장소 Import나 ORM 공유를 허용하지 않는다. In-process Test Double은 계약을 검증하는 목적에서만 사용한다.

**Guard:** DB 계정·환경변수·Cross-service FK/직접 SQL은 SoR 별로 격리. API 입력/출력은 tenant, company, principal, Project scope, version/hash, trace, idempotency, appropriate contract evidence를 검증한다.

### ADR-P1-06 — Frozen Platform & NSL compatibility

**Decision:** NeX Platform v2.1 Frozen에 따른 AE/IA/PA, WC, OA, WA, NSL 실행과 Delegation/Claim/Result 흐름을 유지한다. 새로운 재무 업무는 EOS API·Skill/Tool Binding의 additive 확장으로만 구현한다.

**Guard:** 기존 P8/Golden A `FINANCE.CREATE_VOUCHER_DRAFT` v1, `eos_voucher_draft` DRAFT-only, 기존 Approval/Idempotency/Reconcile 계약 및 Signed Skill Artifact에 하위 호환성 손상을 주지 않는다. NSL WRITE OperationKind에 `POST`를 임의 추가하지 않는다. Journal 생성은 admitted `WRITE CREATE`의 단일 EOS 원자적 실행으로 표현한다.

### ADR-P1-07 — Independent approvals retained

**Decision:** `기안·품의 Business Approval` → `회계 담당자 Human Accounting Approval` → `EOS Atomic GL Posting`을 서로 다른 승인·실행 단계로 유지한다. NSL WRITE admission/approval은 사람의 회계 승인을 대체하지 못한다.

**Guard:** 정확한 문서 Revision/Hash·금액·회사/Project Scope·현재 OA 승인권한·Maker/Checker Separation-of-Duties·기안서 승인한도를 EOS가 확인해야 한다. 승인 없이 `POSTED` 불가. 회사 공용전표는 실제 `COMPANY`/`PROJECT_SET` Scope로 승인하고, 임의 가짜 Project를 붙이지 않는다.

### ADR-P1-08 — Posting transaction boundary

**Decision:** 동일 EOS PostgreSQL DB Transaction에서 ApprovalAcceptance, DocumentConsumption, immutable PostedJournal/Lines, VoucherCandidate state, BusinessOperation/Idempotency/Outbox를 원자적으로 Commit한다. WC/OA와의 DB 간 글로벌 ACID를 가정하지 않고 검증된 이벤트/Proof를 수용한다.

**Guard:** Timeout/ACK loss/retry에서 `UNKNOWN_COMMIT_STATE`를 은폐하지 않고 EOS 조회·대사를 수행한다. POSTED 수량은 0 또는 1. 승인만 완료된 전표는 GL/P&L 실제 실적으로 인식하지 않는다. 오류 정정은 삭제가 아닌 새 역분개.

### ADR-P1-09 — Project P&L / allocation ownership

**Decision:** Project 손익은 EOS의 POSTED GL 및 정해진 수익/원가 적격성으로부터 구성한다. 직접귀속과 공용 배부를 명확히 구분하고, AllocationPlan/Batch/Line은 승인된 결정적 규칙으로 계산한다. Project/NVT projection은 재구축 가능하며 GL의 대체 원장이 아니다.

**Guard:** 원천 GL 금액 보존, 이중 계상 방지, 미배부금액 표시, 실제/예산/잠정 수치 구분, event watermark와 staleness 노출, 개인 급여 역산 방지. Project/Company OA scope 없는 P&L 조회 금지.

### ADR-P1-10 — FX Phase-1 P0 retained

**Decision:** 외환 거래처리를 Phase-1 필수 Scope로 유지. 거래통화/기능통화 금액 분리, 시장 매매기준율(및 해당 통화의 재정된 매매기준율) 출처·공표 회차·날짜·Snapshot Hash 보존, 거래일 최초 인식, 외화채권·채무 결제와 기말 평가 및 실현/미실현 환차손익, 회사 회계/세무 Policy 분리.

**Guard:** 외화 매매기준율을 모든 회계 상황에 무조건 적용하는 단일 규칙으로 단순화하지 않는다. 회사가 승인한 정책과 K-IFRS/세무 요건, 실제 결제환율 차이를 검증한다. Binary float 대신 Decimal/NUMERIC. 외화 취득 재고는 그 자체로 Project 비용이 아님.

### ADR-P1-11 — Project Agent vertical slice first

**Decision:** PA는 기존 AE Registry/Runtime→WC Work/Claim→OA/NSL/EOS API→WA Evidence를 사용한다. D12 Project BusinessReadiness(필수 FL 작업코드 5개, PM/Member/role, Project hierarchy)를 E2E 초기 단계에 검증하고, 자연어 요청과 연결하여 GL/Allocation/P&L까지 실제 동작하는 한 경로를 먼저 확보한다.

**Guard:** 조기 Demo E2E는 단계적 프로토타입일 수 있지만, 정식 Phase-1 완료로 표시하려면 FX/보안/승인/원장/대사/음수 테스트를 모두 통과해야 한다. 외부 Provider·승인·테스트 데이터에서 모의 여부를 정확히 표시한다.

### ADR-P1-12 — Git short branch / gated merge

**Decision:** 각 Slice는 NeX `master`에서 분기한 단기 `feat/eos/...`, `feat/pa/...`, `feat/mybee/...`, `test/...` 브랜치에서 구현하고 정해진 Gate를 통과한 후 `master`에 병합한다. 기능 미완성이면 PR 범위를 쪼개거나 미활성화된 추가 API/Config로 분리하고 영구 장기 브랜치를 두지 않는다.

**Guard:** Golden A/NSL/API 변경·보안·DB Migration이 포함된 PR은 Checkpoint/Full/Pg Gate로 조기 승격. Test DB에서만 Migration/결함 주입; Prod에 미검증 DDL 적용 금지. Branch protection 현황은 Admin이 별도로 확인한다(현재 강제 규칙 설치를 보장하지 않음).

### ADR-P1-13 — No mandatory cross-repo PR for Phase-1

**Decision:** 이전 Repository Governance PAD의 `NeX provider PR → 별도 MyBee consumer PR`은 Phase-1의 필수 경로에서 제외. 같은 NeX 저장소에서 Canonical EOS Contract 변경과 MyBee Consumer/API Integration Test를 동일 PR 또는 의존 PR 체인으로 관리한다. NSL/Blueprint의 독립 권한은 그대로다.

**Guard:** Repository가 같아도 Provider/Consumer 테스트를 둘 다 수행하고 계약 버전·Skill Artifact Digest·DB Migration을 기록한다. 별도 NSL wheel 변경이 필요하면 NSL 저장소의 독립 입장/배포 절차를 따르며 Frozen Amendment 검토.

### ADR-P1-14 — Profiles and release topology

**Decision:** `NeX + EOS 최소업무` 시험 환경과 `NeX + EOS + MyBee Phase-1` 통합 시험 환경을 동일 EOS 코드베이스와 서로 다른 구성/데이터 프로파일로 마련할 수 있게 설계한다. Runtime Feature flags, 테스트 시드/카탈로그, 권한/설정은 명시적으로 Versioned한다.

**Guard:** `EOS Lite`/`EOS Full` 포크 또는 이미 동작하는 런타임 전환 스위치로 오인하지 않는다. 기능/환경별 필요한 운영 Profile은 실제 구현 Slice에서 승인 후 추가. 환경 간 DB·승인·원장 데이터 혼용 금지.

### ADR-P1-15 — Traceability and completion evidence

**Decision:** SRS 116/116, 기존 S0~S8 Packet 37/37, 18 PG fault, 12 E2E를 변경하지 않는다. 각 Packet의 `physical_repo`를 Phase-1 동안 NeX로 임시 Override하고, `logical_owner` 및 SRS/Acceptance 참조는 보존한다. 새로운 MyBee Supplemental MB 13개는 제품 필수 기능에 필요한 것만 재배치·선별한다.

**Guard:** 기계 판독되는 Ownership Override Manifest는 원래 v1.1 JSON을 덮어쓰지 않는다. 실제 구현 Slice 별 source hash/commit, 테스트 결과, PostgreSQL instance, 안전 실패 상태, Golden A 회귀, Acceptance sign-off가 있어야 `DONE`으로 표시한다.

### ADR-P1-16 — Separation defer / re-evaluation trigger

**Decision:** EOS 별도 Repository 추출과 MyBee 독립 배포/저장소 이관은 Phase-1 Closure 후 Architecture Review Gate에서 결정한다. 필요 시 Closure 이전에도 정량적 위험/외부 고객/보안 요구가 생기면 앞당길 수 있다.

**Guard:** 결론을 미리 `MUST EXTRACT`로 두지 않는다. 후보는 유지, MyBee만 별도 Repo로 이전, EOS만 독립 Repo로 이전, EOS/MyBee 모두 이전. 재평가에 실제 코드 의존성·통합/릴리스 주기·테스트 성과·운영 비용 증적을 요구한다.

### ADR-P1-17 — Zero duplicate GL and secured payroll

**Decision:** MyBee Payroll/Purchase는 EOS에 전표 생성을 의뢰하고 자체 회계원장/기표 상태를 정본으로 갖지 않는다. 개인급여·사원 민감자료는 Domain에서 제어하고, EOS는 승인된 원가·배부 기준과 제한된 조회만 처리한다.

**Guard:** MyBee 급여 소스가 원천비용으로 전달되더라도 `POSTED` 적격 전표와 Allocation Ledger 기준이 충족될 때만 실제 P&L에 반영한다. 추정·예산·미승인 값은 명확히 별도 표시. OA가 허용하지 않는 인사/급여 개인 데이터는 IA/PA/P&L 결과에 유출하지 않는다.

### ADR-P1-18 — Rollback and extraction reversibility

**Decision:** 공통 재무 SoR는 기존 EOS API·Migration 계보로 유지하고, MyBee 전용 패키지는 EOS 내부 ORM/DB Dependency 없이 독립 설치 가능한 형태로 설계하여 나중에 이동할 수 있게 한다. Repo 분리 직전에는 신규 고위험 금융 기능의 Merge를 잠시 중지하고 Contract/Golden A/DB 전환 계획을 검증한다.

**Guard:** 이미 POSTED 된 Journal은 Git Revert/DB Rollback의 대상이 아니다. 수정은 승인된 역분개와 보정 전표. DB Schema Migration 되돌리기 가능성은 버전별 데이터 변환·복구 계획을 별도 검토한다. 코드 롤백과 업무 원장 롤백을 혼동하지 않는다.

---

## 4. Functional SoR and authority matrix (Phase-1)

| 영역 / 행위 | SoR/정책 Owner | 실행 / 통합 | 허용 API 범위 | 금지 |
|---|---|---|---|---|
| 로그인·Principal·RoleBinding·Authorization | **OA** | AE/PA, WC, EOS, MyBee | OA PDP/introspection | EOS나 MyBee가 OA 역할을 임의 복제 |
| 직원 기본정보·소속 및 조직 운영 원장 | **EOS(업무 Master)** | MyBee 인사 Domain은 변경 요청 및 업무 절차 실행 | 조직·Employee Master canonical API(추가 구현 필요) | OA user와 Employee PII 동일 테이블로 결합 |
| 결재 WorkItem·담당자 배정·Human Decision | **WC** | EOS Business Approval/Accounting Approval Adapter | WC Work/Approval API | MyBee 단독 DB 상태로 승인 간주 |
| 기안·품의 최종 업무승인 Proof | **EOS** (WC 수행 증거 연계) | MyBee Document/Form | EOS approved-document acceptance API | 회계 승인 또는 NSL 승인과 혼합 |
| Project/NVT/Member/BusinessReadiness | **EOS** | PA/IA, D12 Domain | EOS Project API, WorkCodeSet | Project Owner를 인증/보안권한으로 오용 |
| 계정과목·회계기간·환율 정책/스냅샷 | **EOS** | MyBee D04 승인된 Source/Seed 제공 | EOS Account/Period/FX API | 임의 미승인 환율·계정 코드 적용 |
| VoucherCandidate/회계승인/Posting/GL | **EOS** | AE/NSL & WC/OA | EOS finance v2 Canonical API | MyBee 직접 SQL/이중 원장 생성 |
| CostSourcePool/Allocation/Budget/P&L | **EOS** | D08/D15 Source 어댑터, 경영진 IA READ | EOS guarded Cost/P&L API | GL 기반이 아닌 확정 손익 표시 |
| 급여계산·공제·인사·구매·총무·자금 업무 | **MyBee Domain** | PA/IA가 승인된 Domain Skill 실행 | MyBee Domain API + EOS Business API | Platform `_shared`에 HR/Payroll 정책 내장 |
| Skill 검증/WRITE 실행/위임 실행 | **AE·NSL·OA·WC** (Frozen) | MyBee Skill Pack/Binding | Admitted Skill / Canonical Tool | NSL 언어 내 사무업무 전용 하드코딩 |

**정의:** 동일 Repository 안에 존재한다는 사실은 동일 Database Transaction을 뜻하지 않는다. EOS 단일 DB의 GL Posting만 지역 ACID이며, WC/OA/WA/AE 경계는 검증된 이벤트·Proof·Idempotency/대사로 일관성을 확보한다.

---

## 5. Physical layout and extraction-ready code organization

### 5.1 유지할 EXISTING 경로

```text
2607_nex_platform/
  services/nex-eos/nex_eos/
    app.py
    dependencies.py
    voucher_commands.py
    vouchers.py
    business_transactions.py
    approval_transitions.py
    projects.py
    account_api.py
  database/nex-eos/migrations/2500_...sql ... 2515_...sql
  services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py
  services/nex-ae-api/nex_ae_api/nsl_eos_post_write_verification.py
  services/nex-ae-api/nex_ae_api/nsl_eos_reconciliation.py
  contracts/openapi/nex-eos.openapi.yaml
  contracts/schemas/service/nex_eos/
  scripts/quality/run_slice_gate.sh
  scripts/quality/run_checkpoint_gate.sh
  scripts/quality/run_quality_gate.sh
  tests/
```

### 5.2 Phase-1 신규 경로 — PROPOSED ONLY

```text
2607_nex_platform/
  domains/mybee/                       # 제품 독립을 위한 업무규칙 경계
    README.md                          # Domain owner, import policy, boundaries
    catalog/                           # FL WorkCode 정의/버전, 원본 해시
    skills/                            # Signed Skill Packs, FL→Tool Binding
    templates/                         # 기안·품의, Project 업무 템플릿
    integrations/                      # D08, D15 source/evidence adapters
    config/                            # Domain-specific approved seeds, NEVER secrets
    presentation/                      # API/UX viewmodels, 개인급여 미공개 정책
  docs/mybee_phase1/                   # SRS, Change Ledger, decision, test evidence
  tests/mybee_phase1/                  # 공개 API/Skill/직접 DB 접근 금지 테스트
  apps/mybee-web/                      # Optional: 별도 UI가 필요한 시점에만 승인 후 생성
```

위 신규 경로는 **현재 소스에 존재한다고 주장하지 않는다.** `domains/mybee/`는 라이브러리·도메인 아티팩트를 우선 담고, 독립 프로세스/DB가 필요한 Domain Service가 실제로 나타나면 `services/mybee-ax/`(별도 서비스·DB·API)는 그때 별도 승인한다. 초기에는 기존 AE Web/API 재사용이 우선이며 UI 복제가 기본값이 아니다.

### 5.3 Import / Data Boundary guard (automated)

```text
ALLOW domains/mybee → contracts/schemas (schema validation), public REST clients
ALLOW domains/mybee → admitted NSL Skill metadata + runtime published API
DENY  domains/mybee → services/nex-eos/nex_eos/private ORM/repositories
DENY  domains/mybee → database/nex-eos/ SQL DDL, direct connection/DSN
DENY  domains/mybee → services/nex-oa/... internal storage / WC storage
DENY  services/_shared → domains/mybee payroll/HR business logic
DENY  services/nex-eos → domains/mybee FL policy implementation
ALLOW tests → contract stubs and read-only guarded DB assertions after public E2E flow
DENY  E2E runner → direct runtime-transition SQL INSERT/UPDATE/MERGE after public request
```

Target gating examples (not yet implemented): AST/import lint, environment-scan for EOS DB DSN in MyBee package, DB connection permission test, API contract compatibility tests and P8 regression. No claim that `CODEOWNERS`, new CI or Phase-1 feature flags are already configured.

### 5.4 Minimal deployment setups, no duplicate enterprise truth

| Profile (proposed) | NeX Core | EOS implementation | MyBee | Goal |
|---|---|---|---|---|
| `PA_DEV_CORE` | AE/OA/WC/WA/NSL | **Same `nex-eos` code**, minimum org/Project/approval seed | Optional test work-code pack | PA runtime & organizational authorization tests |
| `MYBEE_P1_INTEGRATION` | AE/OA/WC/WA/NSL | **Same `nex-eos` code**, GL/FX/Allocation APIs enabled only when developed and gated | Minimal D04/D12 plus D08/D15 evidence | Actual Phase-1 end-to-end acceptance |
| `PRODUCTION_CANDIDATE` | Gated build(s) | Single authoritative EOS DB per entity | Approved production-ready package | Separate operational readiness / security / accounting sign-offs |

**Caution:** 현재 이러한 Profile ID나 활성화 스위치가 이미 구현되어 있다는 의미가 아니다. 설계 제안이며 Config/Seed/Profile 검증은 S0 이후 작업이다.

---

## 6. Phase-1 Scope and delivery strategy

### 6.1 End-to-end target outcome

1. EOS에서 직원/조직/법인·Project 계층/PM/Member/Project work-code Set을 구성하고 D12 필수 업무코드 5종의 배정 상태를 확인한다.
2. 사용자가 IA에게 자연어로 Project 관련 비용/구매/업무 처리를 요청한다. PA가 WC의 위임·Claim을 통해 실행 계획/작업을 수행한다.
3. D04/D15 최소 Domain Template에서 기안·품의 제출, WC Human Business Approval 완료, EOS ApprovedDocument Proof 검증이 수행된다.
4. EOS는 승인된 회사/Project Scope, Account, AccountingPeriod, FX RatePolicy/RateSnapshot 기준으로 VoucherCandidate v2를 생성·검증한다.
5. OA authorization을 다시 확인한 회계담당자의 Human Accounting Approval을 받은 뒤, AE/NSL이 EOS canonical `APPROVE_AND_POST` 단일 WRITE를 실행한다.
6. EOS `POSTED` Journal/Line은 같은 EOS DB에서 Idempotency/ApprovalAcceptance/Outbox와 원자적 Commit되고, 적격 비용만 Cost SourcePool에 귀속된다.
7. AllocationPlan/Batch가 직접원가/공용비용을 Project에 결정적으로 배분하고, Project/NVT 손익을 조회한다. 최소 Watermark/staleness·예산대비·미배부를 표시한다.
8. USD 등 외화 거래는 거래통화·기능통화·승인된 매매기준율 Snapshot·결제/기말 환차손익을 검증한다. 실거래 환율/세무평가 정책은 거래 성격에 따라 구분한다.
9. PA가 업무 결과/검증증적을 WA에 남기고, 경영진 IA는 authorized Project P&L을 조회한다. Sensitive payroll은 프로젝트/조직 단위로 보호한다.

### 6.2 Two delivery milestones

| 마일스톤 | 목적 / 허용 주장 | Mandatory Proof |
|---|---|---|
| **M1: Early Integrated Vertical Slice** | 실제 IA/PA→승인→검증된 EOS 단일 GL 거래→Project Allocation/P&L의 최소 연결. 데모/PoC 결과임을 표기 | 공개 API E2E trace, 1 POSTED journal, 합계 보존, 기존 Golden A 영향 없음, TestDB identity |
| **M2: Formal Phase-1 Closure** | D04/D12 SRS의 필수 Accounting/FX/Approval/Project scope와 모든 Gate를 충족한 정식 기능 완성 선언 | 116 SRS 추적, 18 PG fault, 12 E2E, OA/PII/SoD/FX/period/closure, Source PDF/회계 정책 승인, Full Gate |

M1에서는 승인 절차를 생략해서 데모를 빨리 만들지 않는다. Test Fixture로 업무/환율 소스는 대체할 수 있어도 EOS PostedJournal의 안전속성은 실제 PostgreSQL에서 검증해야 한다. E2E Golden Journey는 실제 Platform process의 전이만 허용한다.

### 6.3 Scope of data and source adapters

- MyBee D08 Payroll의 완전한 급여·세금·사대보험 엔진은 Phase-1 범위 외일 수 있으나, **승인된 소스 증적에서 Project 인건비를 안전하게 EOS로 인계하는 최소 계약**은 필요하다.
- D15 Purchase도 전체 조달/재고 시스템 대신 승인된 구매/매입 소스·재고와 비용인식의 차이를 검증하는 Fixture/Adapter로 시작한다.
- K-IFRS 채택 계정표와 승인된 환율 Provider/고시 회차, 회사 회계·세무 평가정책은 EOS의 Versioned Master/Approval Gate를 통과해야 한다.
- 적격한 `POSTED` GL 이전 데이터는 Forecast/Provisional로 구분하고, 실제 손익과 합산하지 않는다.

---

## 7. Implementation Slice Plan v1.1 — explicit Phase-1 override

### 7.1 Rules for preserving historical artifacts

- **원본 유지:** `MyBee_D04_D12_EOS_Implementation_Slice_Plan_v1.0.md`, `NeX_MyBee_D04_D12_EOS_Implementation_Slice_Plan_v1.1.md`, v1.1 Repository Ownership Matrix JSON은 삭제·수정하지 않는다.
- **본 ADR의 우선순위:** 동일 Phase-1 작업에 대해 v1.1 JSON의 `primary_repo=2611_MyBee_Service`와 `cross_repo_pr_protocol` 강제 부분만 Override한다. Domain Owner·SRS ID·Acceptance 및 EOS 서비스 자체 소유권은 그대로다.
- **원본 37개 모두 NeX `master` 기반 단기 브랜치에서 수행:** 이미 v1.1에서 NeX primary인 32개는 변경 없음. MyBee primary 5개는 동일 저장소의 `domains/mybee/` 또는 기타 승인된 독립 모듈로 재배치한다.
- **부가 MyBee 작업 13개:** 별도 저장소 Bootstrap/Release/CI 선행조건은 DEFER, 도메인 업무 구현/테스트/Skill 문서 중 M1/M2에 필요한 부분만 `domains/mybee` 하위로 재배치한다. 기존 MB ID는 보존한다.
- **Provider/Consumer 의미적 분리 유지:** `S6-04N` EOS SourcePool API vs `S6-04M` MyBee Payroll/Purchase Adapter; `S8-01N` Canonical Tool Schema vs `S8-01M` MyBee Skill Pack. Git Repository만 같고 소유 파일·CODEOWNERS·CI Gate는 구별한다.
- **`G-CROSSREPO-E2E` 개명하지 않음:** 기존 테스트 식별자 보존, Phase-1에서는 **Cross-Package E2E**로 실행한다. 이름 유지는 Traceability 보존을 위함이며 별도 Repo 존재를 전제하지 않는다.
- **신규 EOS Migration 2516~2527은 PROPOSED:** 실제 HEAD 검증 후 기존 서비스 전용 Migration 트랙으로 생성. 이미 마이그레이션이 적용된 것처럼 표시하지 않는다.
- **새로운 v1.2 Implementation Plan을 작성할 때:** 본 ADR의 Phase-1 Override를 최우선으로 적용하되, v1.0/v1.1의 원본 ID/의존성을 보존하고 기록한다.

### 7.2 37개 패킷 단위 Ownership Override (요약)

모든 하위 위치는 **물리적인 해당 파일이 이미 존재한다는 뜻이 아니라 작업 목표 디렉터리 제안**이다. 각 패킷의 기존 소스·신규 Migration·SRS·pytest·Gate 세부 내용은 v1.1 계획 및 JSON이 권위 있는 원본이다.

| Packet | 기존 작업 | v1.1 Owner → Phase-1 Repository | Phase-1 Target Area (PROPOSED 포함) | Gate 유지 |
|---|---|---|---|---|
| `S0-01` | Frozen/HEAD·DB 기준선 고정 | NeX/EOS → **NeX monorepo** | `docs/mybee_phase1/ — 기준선·추적성·승인 원장 (제안)` | G-ARCH |
| `S0-02` | P8 Golden A 및 기존 승인 회귀 기준선 | NeX/EOS → **NeX monorepo** | `docs/mybee_phase1/ — 기준선·추적성·승인 원장 (제안)` | G-V1 |
| `S0-03` | 요구사항 추적·소스 원문·변경통제 Gate | NeX/EOS → **NeX monorepo** | `docs/mybee_phase1/ — 기준선·추적성·승인 원장 (제안)` | G-ARCH, G-SRC-PDF |
| `S1-01` | LegalEntity와 ProjectCompanyBinding | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/; domains/mybee/catalog/ (제안)` | G-MASTER, PG-FK |
| `S1-02` | K-IFRS 채택 계정표/승인 릴리스·PostingRule | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/; domains/mybee/catalog/ (제안)` | G-COA, PG-ACCOUNT |
| `S1-03` | AccountingPeriod·Close/Post 동시성 기반 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/; domains/mybee/catalog/ (제안)` | G-PERIOD, PG-RACE |
| `S1-04` | 매매기준율 정책·FX RateSnapshot·Feed | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/; domains/mybee/catalog/ (제안)` | G-FX, G-COA, PG-FX |
| `S1-05` | D12 필수 5 FL코드 및 BusinessReady Gate | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/; domains/mybee/catalog/ (제안)` | G-PROJECT, PG-WORKCODE |
| `S1-06` | Project WorkAssignment·Grade/MD 계획 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/; domains/mybee/catalog/ (제안)` | G-PROJECT, G-PRIVACY |
| `S2-01` | 기안/품의 ApprovedDocumentEnvelope | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + contracts/; domains/mybee/workflow/ (제안)` | G-DOC, PG-PROOF |
| `S2-02` | 회사/다수 Project ScopedApprovalCase v2 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + contracts/; domains/mybee/workflow/ (제안)` | G-HUMAN, PG-SCOPE |
| `S2-03` | 회계 Human SoD·OA/WC 이벤트 어댑터 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + contracts/; domains/mybee/workflow/ (제안)` | G-HUMAN, PG-OA |
| `S2-04` | 품의 승인금액 소비·중복청구 Guard | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + contracts/; domains/mybee/workflow/ (제안)` | G-DOC, PG-CONCURRENCY |
| `S3-01` | VoucherCandidate v2 불변 Revision/Line | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + contracts/ (VoucherCandidate v2)` | G-CANDIDATE, G-V1 |
| `S3-02` | Candidate 회계규칙·FX·기간/균형 검증 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + contracts/ (VoucherCandidate v2)` | G-FX, G-CANDIDATE |
| `S3-03` | Review Submit/Return/Invalidate 상태 머신 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + contracts/ (VoucherCandidate v2)` | G-CANDIDATE, G-HUMAN |
| `S4-01` | Accounting Proof 수용·현재 OA 재검증 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/ (Posting)` | G-HUMAN, G-GL-ACID |
| `S4-02` | Immutable PostedJournal·JournalLine/DB 보호 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/ (Posting)` | G-GL-ACID, PG-IMMUTABLE |
| `S4-03` | Posting 원자적 단일 EOS Transaction | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/ (Posting)` | G-GL-ACID, PG-FAULT |
| `S4-04` | Posting Replay·Outbox·UNKNOWN 복구 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + database/nex-eos/ (Posting)` | G-GL-ACID, G-RECOVERY |
| `S5-01` | 역분개·정정 처리 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + services/nex-ae-api/ (FX/Reconcile)` | G-REVERSAL, PG-IMMUTABLE |
| `S5-02` | 외화 화폐성 항목 기말평가 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + services/nex-ae-api/ (FX/Reconcile)` | G-FX, PG-FX-CLOSE |
| `S5-03` | Period Closing Gate·외화 결제·환차손익 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + services/nex-ae-api/ (FX/Reconcile)` | G-FX, G-PERIOD |
| `S5-04` | Journal Verify/Recon/GL 조회·오류 복구 | NeX/EOS → **NeX monorepo** | `services/nex-eos/ + services/nex-ae-api/ (FX/Reconcile)` | G-RECOVERY, PG-QUERY |
| `S6-01` | POSTED GL SourcePool 적격성 | NeX/EOS → **NeX monorepo** | `services/nex-eos/; domains/mybee/integrations/ (제안)` | G-ALLOCATION, PG-POOL |
| `S6-02` | Allocation Plan 릴리스·배부 정책 | NeX/EOS → **NeX monorepo** | `services/nex-eos/; domains/mybee/integrations/ (제안)` | G-ALLOCATION, PG-POLICY |
| `S6-03` | Deterministic Allocation Batch·대사 | NeX/EOS → **NeX monorepo** | `services/nex-eos/; domains/mybee/integrations/ (제안)` | G-ALLOCATION, PG-CONSERVE |
| `S6-04` | D08 Payroll / D15 Purchase 최소 소스 어댑터 | MyBee Domain → **NeX monorepo** | `domains/mybee/integrations/{payroll,purchase}/ (제안)` | G-ALLOCATION, G-PRIVACY |
| `S7-01` | D04 Budget SoR / D12 Project Budget Link | NeX/EOS → **NeX monorepo** | `services/nex-eos/; domains/mybee/presentation/ (제안)` | G-BUDGET, PG-BUDGET |
| `S7-02` | Project P&L Query/Projection·Watermark | NeX/EOS → **NeX monorepo** | `services/nex-eos/; domains/mybee/presentation/ (제안)` | G-PNL, PG-PROJECTION |
| `S7-03` | Executive P&L 보안/소인원 역산 방지 | NeX/EOS → **NeX monorepo** | `services/nex-eos/; domains/mybee/presentation/ (제안)` | G-PRIVACY, PG-RLS |
| `S7-04` | NVT 롤업·Project 종결/미정산 검증 | NeX/EOS → **NeX monorepo** | `services/nex-eos/; domains/mybee/presentation/ (제안)` | G-PNL, G-PROJECT |
| `S8-01` | NSL Tool JSON Schema·Registry·Skill Pack | MyBee Domain → **NeX monorepo** | `contracts/schemas/service/nex_eos/ + domains/mybee/skills/ (제안)` | G-ARCH, G-NSL |
| `S8-02` | AE Binding·NSL Postwrite Verify/Recon | NeX/EOS → **NeX monorepo** | `contracts/ + services/nex-ae-api/; domains/mybee/skills/ (제안)` | G-NSL, G-RECOVERY |
| `S8-03` | Golden E2E: 승인 USD 공용전표→손익 | MyBee Domain → **NeX monorepo** | `tests/ (공개 API/브라우저 진입)` | G-E2E, G-FX |
| `S8-04` | Payroll·Inventory·FX settlement/close E2E | MyBee Domain → **NeX monorepo** | `tests/ + domains/mybee/integrations/ (제안)` | G-E2E, G-PRIVACY |
| `S8-05` | Full Regression·Signoffs·Controlled Release Closure | MyBee Domain → **NeX monorepo** | `docs/mybee_phase1/releases/ (제안)` | G-RELEASE, G-SRC-PDF |

### 7.3 Mainline PR sequences (single monorepo, no long branch)

```text
NeX master (pinned baseline)
  ↓
PR-A: S0-01/02/03 baseline · Frozen/Golden A/SRS · import/DB ownership guard
  ↓
PR-B: S1 Account / LegalEntity / FX / Period / D12 Project Work readiness
  ↓
PR-C: S2 EOS approved-document + company-scope approval (OA/WC integration)
  ↓
PR-D: S3 VoucherCandidate v2, unchanged Voucher Draft v1
  ↓
PR-E: S4 accountant proof + immutable PostedJournal + atomic commit + unknown reconcile
  ↓
PR-F: S6 minimal POSTED GL source/Allocation + S7 Project P&L/read security
  ↓
M1 verified early vertical journey (NO claim of full Phase-1 closure)
  ↓
PR-G: S5 Reversal/Period close/FX remeasurement + remaining S6/S7 governance
  ↓
PR-H: S8 Canonical Tool/AE Binding + MyBee Skill Pack/Adapter + 12 E2E
  ↓
M2 protected PostgreSQL/Golden A/Full Gate + accounting and PDF source approval
  ↓
Phase-1 tag/RC → EOS Extraction Architecture Review Gate (decision NOT predetermined)
```

이 그림은 **논리적 PR 묶음 예시**이다. 한 PR에 여러 Slice를 무조건 묶지 않는다. EOS/API/DB/인증/회계 보안 변경은 기존 NeX 문서의 Gate Cadence 및 Risk-based Full 승격을 따른다. FX P0를 Phase-1 종결 이전으로 유지하고 S5를 생략하여 완료 선언하지 않는다.

### 7.4 Recommended branch model

| 유형 | Branch 예 | Target | Definition of Done |
|---|---|---|---|
| EOS 마스터·계정·FX | `feat/eos/s1-fx-foundation` | NeX `master` | Canonical API v2, pg, FX snapshot, v1 regression |
| Business Approval | `feat/eos/s2-scoped-approval` | NeX `master` | company approval proof, OA current auth, negative tests |
| Voucher/Post | `feat/eos/s4-atomic-posting` | NeX `master` | Zero partial commit, retry/unknown reconcile |
| Project Cost/P&L | `feat/eos/s6-project-allocation` | NeX `master` | Conservation, eligible POSTED source, security |
| MyBee Domain | `feat/mybee/d04-workcode-skill` | NeX `master` | domain directory only, FL catalog/hash and API consumer tests |
| PA E2E | `test/pa-project-pnl-e2e` | NeX `master` | public API journey + Golden A compatibility |

**Rule:** 적절한 기간 동안 완료할 수 없는 큰 작업은 PR 분할, Contract First, 불활성 Feature로 나누되 `master`에 미검증 전표/원장 기능이 활성화되지 않도록 한다. 활성화 여부는 환경별 감사 가능 정책에 따른다.

---

## 8. Acceptance / CI / PostgreSQL Safety

### 8.1 Existing Gate cadence (do not fake PASS)

- Every Slice: `scripts/quality/run_slice_gate.sh` 및 Owner Service regression; 요구 위험도에 따라 `run_checkpoint_gate.sh`, `run_quality_gate.sh`, `validate_contracts.py` 승격.
- Existing Platform guide: Slice/Checkpoint 95% statement /94% branch, Full compatibility 95%/85%. **EOS Phase-1 작업 목표:** 96% statement/94% branch (조직이 별도 확정하면 그 승인된 목표를 따른다).
- DB: `./.venv/bin/python scripts/db/run_migrations.py --service nex-eos --profile test --dry-run` 은 DDL 계획 검증일 뿐 실제 PostgreSQL 성공이 아니다. `NEX_EOS_TEST_DATABASE_URL`을 식별하고 rollback/locking/Unique/Constraint 테스트를 실제 실행해야 한다.
- Golden A: 기존 v1 Draft path가 v2 승인/Posting 의무를 요구받거나 `POSTED`로 의미 변경되면 FAIL. Replay/Approval/NSL wheel는 정상 유지.
- New NSL skill: Canonical Tool types만 사용하고 signature/digest/admission 및 idempotency/commit verification 요구를 통과해야 한다.

### 8.2 Minimum database acceptance invariants

| Gate | Must pass evidence |
|---|---|
| `G-ARCH` | Frozen diff=0, EOS DB/API/Service SoR 단일, import-policy clean, 37/116 mapping |
| `G-V1` | P8/Golden A existing `VoucherDraft v1` unchanged, Signed Skill & NSL Runtime intact |
| `G-PG` | guarded PostgreSQL test DB, 18 error/concurrency cases, posting atomicity and exactly-once |
| `G-NSL` | admitted canonical Tool `CREATE/CREATE_DRAFT/UPDATE` constraints, new Journal create via bound `CREATE` not unknown `POST` |
| `G-CONSUMER` | 모노레포 내 MyBee 패키지 → EOS API consumer tests, schema/negative fixtures |
| `G-BOUNDARY` | MyBee Domain에서 EOS/OA/WC DB/direct private import 0; service-owned migration only |
| `G-CROSSREPO-E2E` | Traceability ID 유지, 실제 의도는 Cross-Package public-API E2E, NSL/PA/EOS/WA complete |
| `G-SRC-PDF` | D04/D12 PDF 원문-WorkCode/SRS 대조, 차이/승인 기록 (현재 미완료) |
| `G-RELEASE` | Accounting Policy/FX Rate Provider 승인, data privacy, full regression, tagged immutable RC |

### 8.3 Public API-first E2E `E2E-D04D12-FX-01` — canonical minimum

**Fixture values are synthetic, not live exchange rates.** 회사 `C`(기능통화 KRW), Project A/B, 업무코드 5종의 배정 완료, USD 10,000.00 비용거래, 승인된 거래일 USD/KRW 매매기준율 Fixture 1,350.20 KRW/USD, 소요비용 A40% / B60%.

| Step | Runtime/evidence | Assert |
|---:|---|---|
| 1 | AE/IA→PA Work/Claim | Project Scope·Role·D12 5 codes, 실제 Runtime 출처 확인 |
| 2 | Business Document→WC BusinessFormal→EOS Proof | COMPANY/PROJECT_SET, Revision/Hash/금액/결재자 권한 유효 |
| 3 | EOS FX Policy/Snapshot | USD 원금/공식 매매기준율 1,350.20/회차/출처/Hash 고정 |
| 4 | EOS VoucherCandidate v2 | Dr/Cr KRW 13,502,000 일치; 회계 승인 전 GL count=0 |
| 5 | WC Human Accountant + OA current auth | Maker-Checker/Scope/Exact CandidateHash; 승인 후에도 GL count=0 |
| 6 | AE/NSL WRITE CREATE→EOS Atomic Posting | `POSTED JournalCount=1`; proof-consumption/idempotency/outbox same EOS transaction |
| 7 | EOS SourcePool/Allocation | 적격 비용 KRW 13,502,000만 배부; A=5,400,800 / B=8,101,200 |
| 8 | EOS Project/NVT P&L READ | A+B=13,502,000, NVT 중복 없음, watermark/권한/급여 보안 |
| 9 | PA WorkResult→WA Evidence | 업무 trace ID와 원장/배부/환율 Snapshot 감사 링크; 무권한 시 필드 축약 |

> **Important:** 이 Fixture는 즉시 비용인식 가능한 용역/경비라고 가정한다. 재고 120개 구매(40+60 소비, 20 잔여)는 별도 케이스에서 소비분만 원가에 반영해야 하며 취득 시점 전액을 P&L 비용으로 인식하면 실패. 환차손익은 지급·마감 재평가 시 별도 전표로 처리한다.

### 8.4 E2E suite preserved

기존 SRS의 `E2E-D04D12-FX-01..03`, `E2E-D04D12-01..09` 12개 시나리오는 변경하지 않는다. 시나리오 ID·케이스 표는 기존 SRS를 Authority로 사용한다. 조기 M1은 최소 한 경로, M2는 모든 필수 경로를 적합한 실데이터 모사·인증된 TestDB 환경에서 통과해야 한다. 실패 주입 시나리오에서는 부분 Journal/중복 승인 소비/음수 잔고/비정상 외화 평가가 없어야 한다.

Golden Journey 증거로 인정하려면 요청은 공개 Platform API 또는 Browser로 시작해야 한다. 실행 중 WC/EOS/WA Runtime Transition을 테스트가 직접 INSERT/UPDATE하지 않는다. Read-only DB assertion과 실행 후 Test Fixture Cleanup만 허용한다.

---

## 9. Risks, mitigations and architectural debt register

| Risk ID | Failure mode | Severity | Mitigation / observable evidence |
|---|---|---|---|
| `P1-R01` | MyBee Domain이 EOS 내부 ORM을 Import하고 분리불가 | High | Import/DSN Boundary Lint, provider API consumer Test |
| `P1-R02` | `master`에 금융 기능이 절반만 구현된 상태로 활성화 | Critical | Closed-default activation, API feature gate, deployment config sign-off |
| `P1-R03` | 분리 유예가 무기한 방치되어 추후 추출 비용 증가 | High | Phase-1 Closure Gate에서 추출 검토 필수, code coupling metrics |
| `P1-R04` | 분리한 Lite/Full의 원장·Approval semantics Divergence | Critical | EOS DB/Migration 1 authority, Profile only, v1 regression |
| `P1-R05` | Golden A Draft를 새 승인/Posting 의미로 침범 | Critical | Exact v1 contract regression, no schema mutation |
| `P1-R06` | 회사 공용전표에 임의 Project ID를 붙여 승인을 우회 | Critical | Company-scoped case + OA scope/SoD + negative cases |
| `P1-R07` | P&L에 미기표/중복 비용 또는 외화 재고 전체 비용이 섞임 | Critical | POSTED GL only, allocation conservation, Source eligibility |
| `P1-R08` | 직원 급여/개인정보 노출 또는 Project 손익 역산 | Critical | Company/Project OA policies, aggregation, suppression tests |
| `P1-R09` | FX 매매기준율 출처/공표 이력 미보존 | High | approved source/policy and immutable RateSnapshot; finance sign-off |
| `P1-R10` | 문서만 완성되고 실제 PA→WA/EOS E2E가 막힘 | High | M1 Vertical Journey early, M2 protected Full Gate |
| `P1-R11` | 테스트 환경과 운영 환경의 EOS 구현/DB 혼용 | Critical | same code different profile, isolated secrets/DB identity |
| `P1-R12` | Repository 변경이 Frozen Architecture 변경으로 오인 | Medium | declared narrow override, controlled amendment escalation |

**Accepted technical debt:** EOS가 NeX Monorepo에 물리적으로 남는 점, MyBee 도메인 패키지의 배포가 플랫폼과 결합되는 점, 최초 Phase-1의 독립 Release/팀 정책을 추후 정해야 하는 점. **Unaccepted debt:** 이중 GL, 결재 생략, OA/WC 권한 대체, direct DB coupling, 미검증 회계 데이터/미승인 FX policy.

---

## 10. Phase-1 completion and EOS extraction architecture review

### 10.1 Precondition to mark Phase-1 DONE

- [ ] 원본 SRS 116개 중 Phase-1 MUST 별 미구현 0, 추적성 해시/테스트 참조 완전 (예외는 책임자 명시 승인). 원본 Scope를 축소해 PASS로 표기하지 않는다.
- [ ] Project Agent / 업무코드 / OA·WC Authorization/Business Proof / Accountant Proof / EOS POSTED GL / Allocation / P&L의 E2E가 실제 TestDB 기반으로 PASS.
- [ ] FX/PERIOD/REVERSAL/SoD/Payroll privacy/Company-scoped approval/Cost eligibility 및 18 PostgreSQL fault suite 통과.
- [ ] 기존 P8/Golden A v1 backward compatibility, NSL Wheel Admission/Tool Contracts, Full Quality Gate 통과.
- [ ] K-IFRS 채택 계정표·외화율 출처·매매기준율 정책·회계/세무 방법·법인 통화·민감정보 권한이 각각 승인되었음.
- [ ] 원본 D04/D12 PDF·DOCX와 WorkCode 계약 비교 및 추적성 차이 해결/승인.
- [ ] 이 버전의 Git SHA/변경 파일/실제 Migration/DB instance/Test evidence/RC 및 운영자 Sign-off 기록.
- [ ] 미기표/미배부/잠정·Budget과 Posted Actual 분리, Project/NVT P&L 대사와 staleness/권한 검증 완료.
- [ ] EOS Repo Extraction Architecture Review 회의/결정 기록이 생성됨 (**Repo 분리 자체의 완료는 필요조건이 아님**).

### 10.2 Decision Gate `ADR-REVIEW-EOS-EXTRACT-P1`

**Timing:** M2 formal Phase-1 closure 후, 별도 제품/고객 요구 또는 과도한 배포·접근권한 결합 등 즉시 위험 발생 시 조기 Review 가능. Review는 별도 Repository 생성/코드 이동과 다르다.

| Review evidence | Metric or fact to record | Why it matters |
|---|---|---|
| Static dependency graph | `nex_eos` 내부 Import 의존성, MyBee→EOS private import count | 실제 추출 난이도 |
| API & compatibility | Canonical endpoints/schema versions, consumer contract failures, NSL lock | 분리 후 하위 호환성 |
| DB & migration | EOS-only tables/migrations, DDL lock/order, finance ledger preservation | 안정적 DB 소유권 이관 |
| PA / MyBee coupling | AE→EOS, PA→WC/OA/WA, MyBee domain integration trace | 실험/운영 분리 비용 |
| Deployment/release | EOS-only 배포 요구, 독립 롤백 필요, 운영 장애 전파 | 독립 서비스의 실익 |
| Owner teams/security | 유지보수 인력·보안 경계·SLA·고객별 설치요건 | 기술 외 의사결정 근거 |
| Quality evidence | Golden A regressions, FX/GL ACID fault tests, E2E outcomes | 추출의 안정성 |
| Cost comparison | 변경량/관측된 복잡성, CI 지연, 배포·운영비 추정 | 시점 및 옵션 선택 |

**Choice A:** NeX Monorepo 계속 (EOS Service 독립성 유지)  
**Choice B:** MyBee Domain만 독립 Repository/Release로 추출  
**Choice C:** EOS만 독립 Repository/Release로 추출  
**Choice D:** EOS + MyBee 각각 독립 제품 추출  
**Choice E:** 추가 관측 필요하므로 Decision 보류 + 재검토 조건 설정

**Any actual extraction must be a *separate* reviewed Architecture/Delivery Change**, not this ADR's hidden instruction. If Frozen SoR/trust semantics would change, controlled amendment is necessary. Acceptance requires pre/post canonical API compatibility, Golden A/PA journey, PostgreSQL posting/reconcile, provider/consumer safety tests and data migration/rollback plan. Never split existing committed GL into divergent SoRs.

### 10.3 Review output format (required)

```yaml
architecture_review_id: ADR-REVIEW-EOS-EXTRACT-P1
phase1_release_sha: "<verified immutable Git commit>"
phase1_e2e_evidence: "<CI artifact and DB identity>"
observed_coupling_report: "<measured dependency report>"
decision: "KEEP_MONOREPO | EXTRACT_MYBEE | EXTRACT_EOS | EXTRACT_BOTH | DEFER_REVIEW"
owner_approval_ref: "<actual decision approver and timestamp>"
planned_cutover_gate: "<if and only if extraction approved>"
```

---

## 11. Reconciled decision ledger with earlier PAD/ISP documents

| Existing document or decision | Prior position | Phase-1 binding interpretation | Status |
|---|---|---|---|
| D04/D12 Accounting Transaction Contract Closure v1.0 | C1~C6 proof/approval/post/allocation invariants | Entirely retained | **UNCHANGED** |
| D04/D12 EOS Pre-Architecture Decision v1.0 | EOS aggregate/DB SoR/atomic posting/FX/Project P&L | Entirely retained | **UNCHANGED** |
| D04/D12 EOS SRS v1.0 | 116 SRS, 18 PG fault, 12 E2E, FX Phase-1 P0 | Entirely retained | **UNCHANGED** |
| D04/D12 EOS Implementation Slice Plan v1.0 | S0~S8, 37 original packets | Scope/IDs/Dependencies retained | **UNCHANGED** |
| Repository Boundary & Branch Governance PAD v1.0 | MyBee independent repo as launch path, NeX core EOS in platform | Domain boundaries retained; **MyBee independent repo mandate deferred** | **PHASE-1 OVERRIDE** |
| Implementation Slice Plan v1.1 Re-baseline | 32 NeX / 5 MyBee primary, 13 MB in new repo, mandatory cross-repo PR | 37 original logical owners retained; all Phase-1 packets target NeX Monorepo; 13 MB selective in-repo modules; cross-repo PR mandate deferred | **PHASE-1 OVERRIDE** |
| Proposed immediate EOS extraction S-1 | EOS extraction before S0 | Explicitly **NOT** a Phase-1 prerequisite | **REJECT AS PRECONDITION** |
| Frozen Agent/NSL/Platform v2.1 | fixed SoR, trust, agent/work, write semantics | Normative authority unchanged | **PRESERVED** |

**Conflict rule:** For Phase-1 Repo/Branch/PR/Code-placement only, follow this ADR over prior Repo PAD/ISP v1.1. For Finance aggregate semantics, approval truth, GL, FX, Project allocation and NSL/WC/OA authority, follow the earlier frozen/domain normative documents. Ambiguous conflict triggers traceable design review; no silent rewrite.

---

## 12. Codex implementation handoff — first actionable packet

**First packet:** `S0-01 Frozen/HEAD·DB 기준선 고정`. No EOS extraction task and no independent MyBee Repo bootstrap as a blocker.

```text
Repo:  nurigitdev/2607_nex_platform
Base:  master (record exact HEAD and git status before work)
Branch suggestion: feat/eos/s0-01
Input authority:
  - NeX Platform v2.1 Frozen
  - D04/D12 EOS Contract Closure, PAD, SRS v1.0
  - ISP v1.0/v1.1 original 37 packets + 116 requirement JSON
  - THIS ADR v1.0 (Phase-1 owner/repo override)
Task:
  1. Validate HEAD, current EOS Migration head and DB test profile.
  2. Pin v1 voucher & Golden A regression evidence (S0-02).
  3. Establish Phase-1 domain/code owner import boundaries.
  4. Validate 37/37 and 116/116 traceability; preserve all source IDs.
  5. Write source/contract manifest and failed-Gate registry.
  6. Open a small PR; run owning-service Slice Gate, escalate as needed.
Never:
  - Move/fork nex-eos; create new EOS SoR or MyBee accounting DB.
  - Modify Frozen NSL language or v1 VoucherDraft semantic.
  - Mark PG/Golden A/FX approved without actual evidence.
Acceptance:
  - Current source SHA, migration inventory, domain boundaries and
    fixed SRS references recorded; no production DB mutation.
```

**Expected follow-up artifact:** `NeX–MyBee D04/D12 EOS Implementation Slice Plan v1.2 — Phase-1 In-Repository Execution Re-baseline`, not a new SRS. v1.2 should materialize the 37-packet override into the Codex packet table and add minimal M1 E2E dependency ordering, preserving all v1.0/v1.1 sources.

---

## 13. Approval record and release statement

| Record field | Current value |
|---|---|
| Phase-1 architecture option | **D — NeX Monorepo development; EOS extraction deferred** |
| Decision state | **Accepted direction** (conversation-level project owner agreement) |
| Repository changes | **None performed** |
| Database changes | **None performed** |
| PostgreSQL acceptance | **Not run in this architecture work** |
| Formal GitHub approval/PR/merge | **Not performed** |
| Frozen Architecture delta | **None requested by this ADR** |
| Phase-1 release | **Not delivered** |
| Required next decision | M2 closure: Keep / Extract MyBee / Extract EOS / Extract Both / Defer |

**Final normative statement:** Phase-1의 성공 기준은 독립 Repository의 개수가 아니라, 권한과 승인에 의해 통제되는 Project Agent 업무가 동일 EOS의 확정 회계 원장을 거쳐 Project별 검증 가능한 P&L에 도달하는지 여부다. Repository 분리는 이 검증 결과에 따라 후속 Architecture Review에서 결정한다.

---

## Appendix A. Evidence / traceability IDs

- Frozen authority: `ADR-P21-APPROVAL-01` (WC+EOS hybrid), `PRESERVE-02` (EOS Business Transaction SoR), `PRESERVE-03` (Commit/Reconciliation).
- Contract: D04/D12 Accounting Transaction Contract Closure C1~C6; D04/D12 EOS PAD v1.0 ADR; `SRS-ARCH-*`, `SRS-FX-001..024`, D04/D12 SRS requirements.
- Implementation: `S0-01..S8-05` (37 actual packet IDs; exact catalog in companion JSON), `MB*` (13 supplemental proposed), Postgres faults 18, E2E 12.
- Core code: `services/nex-eos/nex_eos/`, `database/nex-eos/migrations/`, `contracts/openapi/nex-eos.openapi.yaml`; AE/NSL adapter paths.
- Observed Git HEADs: NeX `5e64fb1f6b9af2198797d1bcdbc82e577b098fbe`, NSL `f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4`, Blueprint `948b50fd43fc4e0f0d3f40ffd6335871ec741559`.
- Financial sample: `E2E-D04D12-FX-01` fixtures from D04/D12 SRS v1.0, no claim of actual exchange-rate evidence.

## Appendix B. Supporting implementation override manifest

`NeX_MyBee_Phase1_InRepo_Ownership_Override_v1.0.json` is an **additive, non-destructive mapping** over v1.1. It does not overwrite v1.1's 37-packet/SRS 116 truth; it maps physical repository to NeX for Phase-1 and retains original logical owners/requirements/gates so Codex can apply precisely the requested change.
