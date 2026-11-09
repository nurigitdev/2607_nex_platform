# NeX–MyBee D04/D12 EOS Implementation Slice Plan v1.1 — Repository Ownership Re-baseline

**Document ID:** `NEX-MYBEE-D04D12-ISP-REPO-REBASELINE-20261109-V1.1`  
**Status:** `CODEx-READY PLANNING BASELINE / REPOSITORIES NOT MODIFIED / EXECUTION NOT VERIFIED`  
**Date:** 2026-11-09 (Asia/Seoul)  
**Supersedes:** v1.0 *only for repository ownership, split PR ordering and CI/release boundaries*. Does **not** cancel, renumber, or overwrite the 37 original implementation packets, 116 SRS requirements, 18 PostgreSQL faults, 12 E2E scenarios or D04/D12 PAD architectural decisions.  
**Authority:** NeX Platform v2.1 Frozen > EOS/NSL canonical and admitted contracts > MyBee business-domain rules.  
**Parent documents:** EOS SRS v1.0; EOS Implementation Slice Plan v1.0; Repository Boundary & Branch Governance PAD v1.0; EOS Source Audit & Gap Analysis v1.0; D04/D12 Pre-Architecture Decision v1.0.  
**Read-only repository verification:** NeX `master@5e64fb1`, NSL `master@f5d899b`, MyBee Blueprint `main@948b50f`; MyBee Service `nurigitdev/2611_MyBee_Service` remains **proposed and not created**. Recheck all HEADs and migrations at actual Codex execution.  

---

## 0. Decision summary and non-negotiable boundaries

**Product boundary = independently owned repository + versioned release; implementation task boundary = short-lived branch + PR.** No long-lived `feature/mybee-phase1` branch of NeX. All canonical EOS Posting/GL, Account/FX, ApprovedDocument, Project/Member, Budget, Allocation and P&L SoR remain in NeX Platform. MyBee owns office-domain WorkCode meaning/templates, presentation, source adapters, drafts and Skills, never a competing EOS GL.

**Frozen:** No changes to NeX Agent v2.1, NSL v0.2.x compiler/runtime or service responsibility map. EOS/WC/OA/AE/WA remain independently owned; approval proof, accountant decision, NSL WRITE approval and PostedJournal are different constraints. No direct SQL from MyBee to NeX service databases; no cross-service DB FK/JOIN.

**Backward compatibility:** Existing P8/Golden A v1 `FINANCE.CREATE_VOUCHER_DRAFT`, existing `eos_voucher_draft` DRAFT check and prior NSL artifacts remain unchanged. Mandatory approved-document and accountant proof belong to the additive v2 path. New immutable journal = governed `WRITE CREATE` with EOS-level atomic posting; do not invent NSL `POST` OperationKind.

### 0.1 Snapshot and current access

| Repository | Branch | Read-only observation | Ownership |
|---|---|---|---|
| `nurigitdev/2607_nex_platform` | `master` | `5e64fb1` | NeX shared Platform/EOS/API/Tool semantic contracts |
| `nurigitdev/2608_nsl` | `master` | `f5d899b` | NSL compiler/runtime; no planned changes |
| `nurigitdev/2611_MyBee_Blueprint` | `main` | **Accessible again** at `948b50f`; D04/D12 PDF + DOCX listed | Authoritative domain design reference, read-only |
| `nurigitdev/2611_MyBee_Service` | proposed `main` | `404 / NOT CREATED` at audit time | Planned MyBee code, policies, Skill Pack, tests, UI |

> Blueprint access recovery is verified, but D04/D12 PDF **page-level** content comparison has not been completed by this GitHub text-only connector. Gate `G-SRC-PDF` remains pending and must be signed off before Product RC. Do not confuse repository access with source-level approval.

### 0.2 Re-baseline counts (not new implementation claims)

| Item | v1.1 invariant |
|---|---:|
| Original EOS packets `S0-01..S8-05` | **37 retained** |
| Original SRS requirement IDs | **116 retained** |
| Owner labels on original packets | **NeX 32 / MyBee 5** |
| Supplemental MyBee packets `MB*` | **13 proposed** |
| Proposed EOS migrations | **2516–2527 (12), NeX only** |
| PostgreSQL fault/concurrency cases | **18 retained** |
| End-to-end acceptance cases | **12 retained** |

No tests or database migrations were executed as part of this planning document. There is no verified branch protection on NeX `master` or the planned MyBee `main` until an administrator confirms actual Rulesets and required checks.

## 1. Ownership matrix and physical layout

| Asset / domain | Canonical owner (Repository) | MyBee consumer or reference role |
|---|---|---|
| Agent execution, WC workflow, OA authorization, NSL admission, WA evidence | NeX / NSL respectively | MyBee calls pinned public/canonical contracts |
| EOS ApprovedDocument, ScopedApprovalCase, accountant proof | NeX | MyBee draft UI, work-specific forms and claim mapping |
| EOS Account/Catalog, Period, FX source snapshots | NeX | MyBee supplies approved policy/COA seed manifests via controlled EOS intake |
| VoucherCandidate v2, Journal/Posting, reversals, FX remeasurement | NeX | MyBee generates governed requests, never own posted GL |
| SourcePool, Allocation, Budget, Project/NVT P&L | NeX | MyBee supplies D08/D15 source evidence and read-only executive UX |
| Project work-code assignment/readiness, member bindings | NeX | MyBee owns FL catalog + project templates + grade/MD costing rules |
| Canonical EOS OpenAPI, JSON schema and Tool semantics | NeX | MyBee consumer assertions, Skill Pack/tool bindings |
| MyBee document drafts, UI, payroll/purchase source adapters | MyBee | EOS receives validated business facts via API |
| D04/D12 source PDFs, original domain blueprint | Blueprint reference | Read-only reference pinned by commit/hash |

### 1.1 Target layout (paths marked PROPOSED until created)

```text
NeX Platform (existing repo)
  services/nex-eos/nex_eos/       # existing EOS + new generic finance aggregates
  database/nex-eos/migrations/   # 2516..2527 planned; owner only NeX
  contracts/openapi/nex-eos.openapi.yaml
  contracts/schemas/service/nex_eos/  # additive provider v2 JSON schemas
  services/nex-ae-api/nex_ae_api/     # canonical NSL/EOS runtime ports
  docs/mybee_d04d12/                 # NeX contract/trace evidence, NOT MyBee app
MyBee Service (NEW PROPOSED repo, not yet created)
  src/mybee_ax/{domain,integrations}/
  catalog/work_codes/              # versioned FL domain catalog
  templates/d12/                   # five required D12 FL codes
  skills/{d04_accounting,d12_project}/
  config/{account_catalog,fx}/    # approved policies/seed manifests, not GL
  apps/mybee-web/                  # proposed domain UX; not nex-ae-web fork
  tests/{contracts,e2e}/
  compatibility/platform.lock.json # exact accepted NeX/EOS/NSL refs
  releases/phase1/compatibility.lock.json
MyBee Blueprint (existing repo: docs/origin only, READ-ONLY)
```

**Rule:** New MyBee code cannot import `nex_eos` internal modules, use `NEX_EOS_DATABASE_URL`, copy EOS migrations, or directly `INSERT/UPDATE` EOS tables. Any such cross-database path fails `G-BOUNDARY`. NSL frozen sources are not edited to add business syntax.

## 2. Pull-request, version and deployment governance

### 2.1 Git rules

1. NeX base is `master`; MyBee Service and Blueprint base is `main`; NSL remains separately versioned on `master`. Product domain ≠ Git branch. Avoid permanent `develop`, `integration/mybee`, `feature/mybee-phase1`.
2. Per reviewable packet, create short-lived `feat/`, `fix/`, `test/`, or `docs/` branches in **owning repo**. Preferred lifetime ≤ 5 working days; > 10 requires split/rebase decision. The packets below have suggested names, not commands already run.
3. One cross-repo change receives shared Change ID and at least two linked PRs when provider + consumer are modified. Review each PR independently with own `CODEOWNERS`, CI artifacts, and machine-validated pinned contract.
4. NeX provider PR with additive API / tool schema and tests comes first. CI builds immutable provider artifact and publishes its SHA/version as a prerelease candidate; MyBee consumer PR pins the artifact and runs negative and E2E tests. Merge independent paths only after their own gates; consumer activation cannot precede provider acceptance.
5. Provider Release→Consumer Lock→Consumer Release is the deployment order. Compatible v2 is additive; old v1 P8/Golden A remains admitted. Production rollback of an accountant-approved posted journal must use governed reversal/fix-forward, never table truncation.
6. New branch protection and required reviewers/checks are **recommended, not presumed configured**. Admin must independently verify Rulesets, status checks and bypass policy.

### 2.2 Generic cross-repository PR chain (DAG)

```text
B-00 (Blueprint main@948b50f is readable; PDF semantic signoff remains open)
   |
N-S0 baseline & P8 v1 regression ---- M-MB0-01 bootstrap (new repo)
   |                                       |
   +-- N-S1..S4 provider PRs ----> immutable EOS v2 RC + schema digest
                                   |
                                   +--> M-MB1/MB2/MB3 consumer PRs
   +-- N-S5..S7 provider PRs ----> domain-safe SourcePool/P&L RC
                                   |
                                   +--> M-MB6/MB7 consumer PRs
   +-- N-S8-01N canonical Tool contracts and N-S8-02 AE adapters
                                   |
                                   +--> M-S8-01M / MB8-01 admitted Skills
   +--------------------- N-Provider E2E <--> M-Consumer E2E
                                               |
                           independent tags/releases + compatibility lock
```

This diagram is a release dependency, **not** a distributed Git commit. Provider-first merge can be incremental behind disabled/guarded capability; consumer tests may use pinned PR artifacts, but may not silently depend on unmerged mutable branch HEAD.

### 2.3 Specific split decisions (correction of v1.0 path hints)

| Parent packet | Provider/NeX sub-PR | Consumer/MyBee sub-PR | Guard |
|---|---|---|---|
| `S6-04` | `S6-04N` generic `FINANCE.COST_SOURCE` / Candidate source API, verified eligibility & tenant/project permission | `S6-04M` D08 payroll and D15 purchasing adapters under `src/mybee_ax/integrations/` | **Never** place `mybee_cost_source_adapters.py` in EOS; private payroll not exposed |
| `S8-01` | `S8-01N` EOS OpenAPI/JSON Schema/semantic Tool contract registry | `S8-01M` MyBee Skill Pack, FL→Tool mapping & signatures | Frozen NSL compiler/runtime and v1 canonical contract unchanged |
| `S8-03` | NeX provider end-to-end Journal/FX/Allocation assertion suite | MyBee public UX/API business journey suite | Neither runner may fabricate WC/EOS/WA state |
| `S8-04` | NeX source intake, privacy, FX settlement/close provider tests | MyBee D08/D15 consumer adapters and business E2E | Do not infer financial proof from MyBee-only fixtures |
| `S8-05` | NeX release manifest/tag, PG protected tests & operator signoffs | MyBee compatibility.lock/tag and consumer signoffs | Two independent RCs; no forced cross-repo merge |

## 3. Codex execution instructions — universal Packet Contract

Before each packet, Codex must (1) refresh exact HEAD, `git status --short --branch`, and owning source paths, (2) read SRS IDs + ADR/Source Audit and current contract versions, (3) declare owner repo, branch, changed files and target Migration, (4) use only EOS authenticated API and admitted NSL types, (5) implement focused unit/API/contract tests + protected PG where required, (6) run Slice Gate and escalated Checkpoint/Full Gate for auth/cross-service/schema risk, (7) record SHA, command, test result, migration identity, immutable proof and diff, (8) open scoped PR with references to consumer provider lock.

**NeX quality commands (existing, example invocation only):**
```bash
scripts/quality/run_slice_gate.sh --service nex-eos \
  --test tests/test_nex_eos_mybee_account_policy.py \
  --coverage-target services/nex-eos/nex_eos/account_catalog.py
scripts/quality/run_checkpoint_gate.sh --test tests/test_nex_eos_mybee_allocation_pg.py
scripts/quality/run_quality_gate.sh
./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/python scripts/db/run_migrations.py --service nex-eos --profile test --dry-run
```
Every new example test/path is PROPOSED until its creating PR lands. `--dry-run` is readiness only and **never** constitutes a real PostgreSQL test PASS. Platform documented quality cadence: owning-service Slice Gate every slice, Checkpoint fifth slice per requirement, Full tenth/closure; escalate early for auth, migrations, cross-service or financial safety.

**MyBee CI commands (PROPOSED for new repo):** `python -m pytest tests/`, contract lock verification, API consumer tests, PII/privacy lint, forbidden `nex_eos`/DB import checks, optional browser E2E. Must not claim currently installed.

**Environment invariants:** `NEX_EOS_TEST_DATABASE_URL` and production EOS credentials never reside in MyBee CI. Provider PG tests must identify test-profile DB and clean only synthetic rows. MyBee receives audience-bound service tokens, not unrestricted EOS DB access. Run protected business journeys through public API/browser, not direct runtime SQL mutation.

## 4. 37 original implementation packets — owner, files, contract, tests, gate

Each below is **the retained v1.0 packet** with v1.1 repository ownership and source relocation. “Existing” refers to recognized source hints on NeX tree (verify again at Codex start). “New” paths are proposals, not files already present. Full authoritative SRS-to-test matrix is included in the companion JSON, without losing any original trace or test ID.

### A. Governance & Baseline (3 packets)

#### `S0-01` — Frozen/HEAD·DB 기준선 고정 | **NeX primary**

- **PR / Branch:** `NEX-s0_01` → `nurigitdev/2607_nex_platform` : `feat/eos/s0-01`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `start`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `docs/frozen/v2.1/10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md` ; `database/nex-eos/README.md`.
- **NeX expected changes (PROPOSED):** `docs/mybee_d04d12/baselines/source_manifest.json` ; `docs/mybee_d04d12/baselines/repo_compatibility_owners.md`.
- **MyBee consumer/domain file candidates (PROPOSED):** `compatibility/platform.lock.json`.
- **API / Tool:** `보안/권한/DB 소유권 검증`; NSL `N/A (runtime tool 미변경)`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_mybee_d04d12_architecture_snapshot.py`; `G-ARCH`.
- **SRS requirements (3):** `SRS-ARCH-001`, `SRS-ARCH-002`, `SRS-ARCH-004`.
- **Exit acceptance:** Frozen diff=0, 실제 master HEAD/계약 해시/마이그레이션 끝번호 기록

#### `S0-02` — P8 Golden A 및 기존 승인 회귀 기준선 | **NeX primary**

- **PR / Branch:** `NEX-s0_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s0-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S0-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/vouchers.py` ; `services/nex-eos/nex_eos/voucher_commands.py` ; `services/nex-eos/nex_eos/approval_transitions.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py`.
- **NeX expected changes (PROPOSED):** `docs/mybee_d04d12/baselines/v1_regression_results.md`.
- **API / Tool:** `기존 /internal/v1/finance/voucher-drafts READ/CREATE`; NSL `FINANCE.CREATE_VOUCHER_DRAFT (v1 unchanged)`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_p8_s15_voucher_draft.py` ; `tests/test_nex_ae_eos_p8_s66_golden_a_commit_journey.py`; `G-V1`.
- **SRS requirements (3):** `SRS-ARCH-005`, `SRS-PRJ-001`, `SRS-VCH-006`.
- **Exit acceptance:** 기존 v1 Draft/DRAFT DB CHECK/ACK·NSL 회귀 실패 0

#### `S0-03` — 요구사항 추적·소스 원문·변경통제 Gate | **NeX primary**

- **PR / Branch:** `NEX-s0_03` → `nurigitdev/2607_nex_platform` : `feat/eos/s0-03`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S0-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `contracts/openapi/nex-eos.openapi.yaml` ; `docs/frozen/v2.1`.
- **NeX expected changes (PROPOSED):** `docs/mybee_d04d12/traceability/requirements.v1.1.json` ; `tests/test_mybee_d04d12_architecture_snapshot.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `docs/traceability/nex_srs_links.json`.
- **API / Tool:** `Schema/Operation registry 충돌 예비검사`; NSL `No new Tool activation`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_mybee_d04d12_traceability.py`; `G-ARCH`, `G-SRC-PDF`.
- **SRS requirements (2):** `SRS-ARCH-003`, `SRS-COM-001`.
- **Exit acceptance:** 116개 요구사항 누락·중복 0; PDF 미검증은 Open Gate로 표기
- **v1.1 guard:** Blueprint GitHub accessible at main@948b50f; PDF assets listed; page-by-page PDF inspection/sign-off remains a distinct source-acceptance gate.

### B. Foundation & FX (6 packets)

#### `S1-01` — LegalEntity와 ProjectCompanyBinding | **NeX primary**

- **PR / Branch:** `NEX-s1_01` → `nurigitdev/2607_nex_platform` : `feat/eos/s1-01`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S0-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/projects.py` ; `services/nex-eos/nex_eos/project_operations.py` ; `database/nex-eos/migrations/2504_eos_project_hierarchy.sql`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/legal_entities.py` ; `services/nex-eos/nex_eos/legal_entity_api.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2516_eos_legal_entity_project_binding.sql`.
- **API / Tool:** `FINANCE.LEGAL_ENTITY.GET; company binding command/query`; NSL `READ: FINANCE.LEGAL_ENTITY.GET`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_legal_entity.py`; `G-MASTER`, `PG-FK`.
- **SRS requirements (4):** `SRS-MST-001`, `SRS-MST-002`, `SRS-MST-004`, `SRS-SEC-009`.
- **Exit acceptance:** 법인 유효기간·프로젝트 법인 귀속 1:1; 가짜 Project 금지

#### `S1-02` — K-IFRS 채택 계정표/승인 릴리스·PostingRule | **NeX primary**

- **PR / Branch:** `NEX-s1_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s1-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/accounts.py` ; `services/nex-eos/nex_eos/account_api.py` ; `database/nex-eos/migrations/2505_eos_account.sql`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/account_catalog.py` ; `services/nex-eos/nex_eos/account_policy_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `config/account_catalog/approved_seed_manifest.json`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2517_eos_account_catalog_accounting_period.sql`.
- **API / Tool:** `FINANCE.ACCOUNT.CATALOG_GET; FINANCE.ACCOUNT.CREATE_APPROVED`; NSL `READ: FINANCE.ACCOUNT.CATALOG_GET; governed CREATE`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_account_policy.py`; `G-COA`, `PG-ACCOUNT`.
- **SRS requirements (5):** `SRS-ACC-001`, `SRS-ACC-002`, `SRS-ACC-003`, `SRS-ACC-005`, `SRS-ACC-006`.
- **Exit acceptance:** 원본 계정표 seed hash·승인; leaf/유효일/통화/monetary 구분

#### `S1-03` — AccountingPeriod·Close/Post 동시성 기반 | **NeX primary**

- **PR / Branch:** `NEX-s1_03` → `nurigitdev/2607_nex_platform` : `feat/eos/s1-03`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/business_transactions.py` ; `services/nex-eos/nex_eos/persistence.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/accounting_periods.py` ; `services/nex-eos/nex_eos/accounting_period_api.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2517_eos_account_catalog_accounting_period.sql`.
- **API / Tool:** `FINANCE.PERIOD.GET; FINANCE.PERIOD.CLOSE (Close gate S5)`; NSL `READ: FINANCE.PERIOD.GET; later governed WRITE`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_period_lock_pg.py`; `G-PERIOD`, `PG-RACE`.
- **SRS requirements (2):** `SRS-PER-001`, `SRS-PER-002`.
- **Exit acceptance:** 동일 period FOR UPDATE 잠금과 OPEN/CLOSING/CLOSED 전이

#### `S1-04` — 매매기준율 정책·FX RateSnapshot·Feed | **NeX primary**

- **PR / Branch:** `NEX-s1_04` → `nurigitdev/2607_nex_platform` : `feat/eos/s1-04`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-01/S1-02`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/accounts.py` ; `services/nex-eos/nex_eos/business_transactions.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_post_write_verification.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/fx_rates.py` ; `services/nex-eos/nex_eos/fx_policy.py` ; `services/nex-eos/nex_eos/fx_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `config/fx/approved_rate_source_policy.json`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2518_eos_fx_rate_policy_snapshot.sql`.
- **API / Tool:** `FINANCE.FX_RATE.IMPORT; FINANCE.FX_RATE.RESOLVE`; NSL `READ: FINANCE.FX_RATE.RESOLVE; approved source WRITE`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_fx_rate.py`; `G-FX`, `G-COA`, `PG-FX`.
- **SRS requirements (11):** `SRS-FX-001`, `SRS-FX-005`, `SRS-FX-006`, `SRS-FX-007`, `SRS-FX-008`, `SRS-FX-009`, `SRS-FX-018`, `SRS-FX-021`, `SRS-FX-022`, `SRS-FX-024`, `SRS-SEC-008`.
- **Exit acceptance:** 공식 출처/고시회차/일자/quote_unit/version·원문 해시·휴일 실패닫기
- **v1.1 guard:** FX rate source and policy version approved; preserve original currency and functional currency, rule selection, snapshot, settlement/revaluation. Do not fabricate rates.

#### `S1-05` — D12 필수 5 FL코드 및 BusinessReady Gate | **NeX primary**

- **PR / Branch:** `NEX-s1_05` → `nurigitdev/2607_nex_platform` : `feat/eos/s1-05`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/projects.py` ; `services/nex-eos/nex_eos/project_operations.py` ; `services/nex-eos/nex_eos/project_memberships.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/project_work_codes.py` ; `services/nex-eos/nex_eos/project_business_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/domain/work_codes.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2519_eos_project_work_code_readiness.sql`.
- **API / Tool:** `PROJECT.WORK_CODE_SET.GET/APPROVE; readiness query`; NSL `READ GET; WRITE APPROVE UPDATE (admitted 0.2.1 only)`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_work_code_ready.py`; `G-PROJECT`, `PG-WORKCODE`.
- **SRS requirements (4):** `SRS-PRJ-002`, `SRS-PRJ-003`, `SRS-PRJ-004`, `SRS-PRJ-008`.
- **Exit acceptance:** FL0012004/005/006/013/026 필수; v1 ACTIVE와 BUSINESS_READY 분리
- **v1.1 guard:** EOS owns project-bound work code assignments and readiness; MyBee owns code catalog/template/policies, never duplicate Project SoR.

#### `S1-06` — Project WorkAssignment·Grade/MD 계획 | **NeX primary**

- **PR / Branch:** `NEX-s1_06` → `nurigitdev/2607_nex_platform` : `feat/eos/s1-06`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-05`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/project_memberships.py` ; `services/nex-eos/nex_eos/project_api.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/project_work_assignments.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/domain/workforce_planning.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2519_eos_project_work_code_readiness.sql`.
- **API / Tool:** `Project work assignment command/query`; NSL `New domain Tool contract after OA admission`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_work_assignment.py`; `G-PROJECT`, `G-PRIVACY`.
- **SRS requirements (2):** `SRS-PRJ-005`, `SRS-PRJ-006`.
- **Exit acceptance:** Grade/MD와 개인 실제급여 분리; OA Scope 필수
- **v1.1 guard:** EOS owns project-bound work code assignments and readiness; MyBee owns code catalog/template/policies, never duplicate Project SoR.

### C. Documents & Human Approvals (4 packets)

#### `S2-01` — 기안/품의 ApprovedDocumentEnvelope | **NeX primary**

- **PR / Branch:** `NEX-s2_01` → `nurigitdev/2607_nex_platform` : `feat/eos/s2-01`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-01/S1-02`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/approval_instances.py` ; `services/nex-eos/nex_eos/approval_transitions.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/approved_documents.py` ; `services/nex-eos/nex_eos/approved_document_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/domain/documents.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2520_eos_document_approval_envelope.sql`.
- **API / Tool:** `BUSINESS.DOCUMENT_APPROVED.GET`; NSL `READ proof by EOS and hash; no direct approval bypass`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_document_envelope.py`; `G-DOC`, `PG-PROOF`.
- **SRS requirements (3):** `SRS-DOC-001`, `SRS-DOC-002`, `SRS-DOC-007`.
- **Exit acceptance:** 최종 BUSINESS_FORMAL proof/문서 revision/첨부/한도/법인 정확 결합
- **v1.1 guard:** Business approval/document signoff != accounting human approval != NSL WRITE approve != GL POSTED.

#### `S2-02` — 회사/다수 Project ScopedApprovalCase v2 | **NeX primary**

- **PR / Branch:** `NEX-s2_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s2-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-01/S2-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/approval_policies.py` ; `services/nex-eos/nex_eos/approval_instances.py` ; `services/nex-eos/nex_eos/business_formal_wc.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/scoped_approvals.py` ; `services/nex-eos/nex_eos/scoped_approval_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/integrations/nex_approval_client.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2521_eos_scoped_approval_case_v2.sql`.
- **API / Tool:** `FINANCE.ACCOUNTING_APPROVAL.REQUEST (v2 case)`; NSL `WRITE CREATE request only; Human WC decision separate`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_approval_company.py`; `G-HUMAN`, `PG-SCOPE`.
- **SRS requirements (2):** `SRS-MST-003`, `SRS-SEC-001`.
- **Exit acceptance:** v1 project_id NOT NULL 유지; COMPANY/PROJECT_SET 회사 기반
- **v1.1 guard:** Business approval/document signoff != accounting human approval != NSL WRITE approve != GL POSTED.

#### `S2-03` — 회계 Human SoD·OA/WC 이벤트 어댑터 | **NeX primary**

- **PR / Branch:** `NEX-s2_03` → `nurigitdev/2607_nex_platform` : `feat/eos/s2-03`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S2-02`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/approval_decision_api.py` ; `services/nex-eos/nex_eos/approval_transitions.py` ; `services/nex-eos/nex_eos/authorization.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/accounting_approval.py` ; `services/nex-eos/nex_eos/accounting_approval_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/domain/accounting_signoff_view.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2521_eos_scoped_approval_case_v2.sql`.
- **API / Tool:** `FINANCE.ACCOUNTING_APPROVAL.REQUEST + WC event`; NSL `No agent self-approve; OA human finance:journal:approve`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_approval_human.py`; `G-HUMAN`, `PG-OA`.
- **SRS requirements (9):** `SRS-APR-001`, `SRS-APR-002`, `SRS-APR-003`, `SRS-APR-005`, `SRS-APR-008`, `SRS-FX-023`, `SRS-SEC-002`, `SRS-SEC-003`, `SRS-SEC-005`.
- **Exit acceptance:** 중복/역순/권한철회/자기승인 거부; 회계 Proof v2
- **v1.1 guard:** Business approval/document signoff != accounting human approval != NSL WRITE approve != GL POSTED.

#### `S2-04` — 품의 승인금액 소비·중복청구 Guard | **NeX primary**

- **PR / Branch:** `NEX-s2_04` → `nurigitdev/2607_nex_platform` : `feat/eos/s2-04`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S2-01/S2-02`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/business_transactions.py` ; `services/nex-eos/nex_eos/approval_instances.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/approved_document_consumption.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2520_eos_document_approval_envelope.sql`.
- **API / Tool:** `Document allowance GET; Consumption EOS-only in S4 Posting`; NSL `READ validation; no stand-alone consumption WRITE`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_doc_consumption_pg.py`; `G-DOC`, `PG-CONCURRENCY`.
- **SRS requirements (3):** `SRS-DOC-003`, `SRS-DOC-004`, `SRS-DOC-005`.
- **Exit acceptance:** 법인·통화별 한도와 source invoice uniqueness; S4와 동일 UoW

### D. Candidates & Validation (3 packets)

#### `S3-01` — VoucherCandidate v2 불변 Revision/Line | **NeX primary**

- **PR / Branch:** `NEX-s3_01` → `nurigitdev/2607_nex_platform` : `feat/eos/s3-01`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-02/S2-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/vouchers.py` ; `services/nex-eos/nex_eos/voucher_commands.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/voucher_candidates.py` ; `services/nex-eos/nex_eos/finance_v2_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/integrations/nex_voucher_candidate_client.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2522_eos_voucher_candidate_v2.sql`.
- **API / Tool:** `FINANCE.VOUCHER_CANDIDATE.CREATE_V2`; NSL `WRITE CREATE_DRAFT; existing v1 unchanged`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_voucher_candidate.py`; `G-CANDIDATE`, `G-V1`.
- **SRS requirements (2):** `SRS-VCH-001`, `SRS-VCH-002`.
- **Exit acceptance:** 사업승인 없이는 후보 생성 0; 회사 공용 헤더 project_id 필수 금지
- **v1.1 guard:** Business approval/document signoff != accounting human approval != NSL WRITE approve != GL POSTED.

#### `S3-02` — Candidate 회계규칙·FX·기간/균형 검증 | **NeX primary**

- **PR / Branch:** `NEX-s3_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s3-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S3-01/S1-04/S1-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/vouchers.py` ; `services/nex-eos/nex_eos/accounts.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/candidate_validation.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/domain/accounting_rules.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2522_eos_voucher_candidate_v2.sql`.
- **API / Tool:** `FINANCE.VOUCHER_CANDIDATE.VALIDATE`; NSL `READ/validation Tool; no GL side-effect`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_voucher_fx_validation.py`; `G-FX`, `G-CANDIDATE`.
- **SRS requirements (8):** `SRS-ACC-004`, `SRS-ARCH-007`, `SRS-FX-002`, `SRS-FX-003`, `SRS-FX-004`, `SRS-FX-010`, `SRS-FX-011`, `SRS-VCH-005`.
- **Exit acceptance:** Dr/Cr 기능통화 균형, immutable FX/rule snapshots, 휴일/단위/미확정 차단
- **v1.1 guard:** FX rate source and policy version approved; preserve original currency and functional currency, rule selection, snapshot, settlement/revaluation. Do not fabricate rates.

#### `S3-03` — Review Submit/Return/Invalidate 상태 머신 | **NeX primary**

- **PR / Branch:** `NEX-s3_03` → `nurigitdev/2607_nex_platform` : `feat/eos/s3-03`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S3-02/S2-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/approval_transitions.py` ; `WC ApprovalWorkItem`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/candidate_review.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2522_eos_voucher_candidate_v2.sql`.
- **API / Tool:** `FINANCE.ACCOUNTING_APPROVAL.REQUEST; candidate review GET`; NSL `WRITE CREATE review case; NO POST on WC result`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_candidate_review.py`; `G-CANDIDATE`, `G-HUMAN`.
- **SRS requirements (1):** `SRS-VCH-004`.
- **Exit acceptance:** 변경 시 승인 무효, immutable revision + compare-and-swap

### E. Atomic Posting (4 packets)

#### `S4-01` — Accounting Proof 수용·현재 OA 재검증 | **NeX primary**

- **PR / Branch:** `NEX-s4_01` → `nurigitdev/2607_nex_platform` : `feat/eos/s4-01`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S2-03/S3-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/approval_transitions.py` ; `services/nex-eos/nex_eos/authorization.py` ; `services/nex-eos/nex_eos/approval_instances.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/accounting_posting_admission.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql`.
- **API / Tool:** `FINANCE.VOUCHER.APPROVE_AND_POST (admission)`; NSL `NSL WRITE R5; OA freshness + exact human proof`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_accountant_proof.py`; `G-HUMAN`, `G-GL-ACID`.
- **SRS requirements (2):** `SRS-APR-004`, `SRS-APR-007`.
- **Exit acceptance:** DOCUMENT_SIGNOFF ≠ ACCOUNTING_POSTING, stale/자기승인 실패닫기
- **v1.1 guard:** Business approval/document signoff != accounting human approval != NSL WRITE approve != GL POSTED.

#### `S4-02` — Immutable PostedJournal·JournalLine/DB 보호 | **NeX primary**

- **PR / Branch:** `NEX-s4_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s4-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-03/S3-02`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/business_transactions.py` ; `2506_eos_voucher_draft.sql KEEP`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/journals.py` ; `services/nex-eos/nex_eos/journal_verification.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql`.
- **API / Tool:** `FINANCE.JOURNAL.GET/VERIFY`; NSL `READ verification + signed journal result`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_journal_immutable_pg.py`; `G-GL-ACID`, `PG-IMMUTABLE`.
- **SRS requirements (1):** `SRS-ACC-007`.
- **Exit acceptance:** JournalHeader/Line 불변 및 UNIQUE posting/period/계정 snapshot

#### `S4-03` — Posting 원자적 단일 EOS Transaction | **NeX primary**

- **PR / Branch:** `NEX-s4_03` → `nurigitdev/2607_nex_platform` : `feat/eos/s4-03`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S4-01/S4-02/S2-04`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/business_transactions.py` ; `services/nex-eos/nex_eos/persistence.py` ; `services/nex-eos/nex_eos/outbox_publication.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/journal_posting.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql`.
- **API / Tool:** `FINANCE.VOUCHER.APPROVE_AND_POST`; NSL `WRITE CREATE immutable journal; no POST OperationKind`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_posting_atomic_pg.py`; `G-GL-ACID`, `PG-FAULT`.
- **SRS requirements (3):** `SRS-ARCH-008`, `SRS-ARCH-009`, `SRS-VCH-003`.
- **Exit acceptance:** ProofAcceptance+Journal+consumption+candidate CAS+Idem+Outbox 전부 1 Commit
- **v1.1 guard:** Business approval/document signoff != accounting human approval != NSL WRITE approve != GL POSTED.

#### `S4-04` — Posting Replay·Outbox·UNKNOWN 복구 | **NeX primary**

- **PR / Branch:** `NEX-s4_04` → `nurigitdev/2607_nex_platform` : `feat/eos/s4-04`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S4-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/business_transactions.py` ; `services/nex-eos/nex_eos/outbox_publication.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_reconciliation.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/journal_operations.py` ; `services/nex-eos/nex_eos/journal_outbox_events.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql`.
- **API / Tool:** `FINANCE.JOURNAL.RECONCILE`; NSL `READ authoritative business operation; NSL typed UNKNOWN`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_posting_replay_pg.py`; `G-GL-ACID`, `G-RECOVERY`.
- **SRS requirements (4):** `SRS-APR-006`, `SRS-ARCH-006`, `SRS-SEC-007`, `SRS-VCH-007`.
- **Exit acceptance:** 20경합 1장, ACK유실 조회, same key/hash replay, outbox 중복 안전

### F. GL Closure & FX (4 packets)

#### `S5-01` — 역분개·정정 처리 | **NeX primary**

- **PR / Branch:** `NEX-s5_01` → `nurigitdev/2607_nex_platform` : `feat/eos/s5-01`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S4-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/vouchers.py` ; `services/nex-eos/nex_eos/business_transactions.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/journal_reversal.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql`.
- **API / Tool:** `FINANCE.JOURNAL.REVERSE`; NSL `WRITE CREATE new approved reversal journal`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_journal_reversal.py`; `G-REVERSAL`, `PG-IMMUTABLE`.
- **SRS requirements (3):** `SRS-DOC-006`, `SRS-FX-016`, `SRS-VCH-008`.
- **Exit acceptance:** 원 GL 변경 0, fresh approval/새 기간, allocation compensation

#### `S5-02` — 외화 화폐성 항목 기말평가 | **NeX primary**

- **PR / Branch:** `NEX-s5_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s5-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S4-03/S1-04`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/account_catalog.py` ; `services/nex-eos/nex_eos/fx_rates.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/fx_remeasurement.py` ; `services/nex-eos/nex_eos/monetary_positions.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql`.
- **API / Tool:** `FINANCE.FX_REMEASUREMENT.RUN`; NSL `WRITE CREATE_DRAFT/CREATE candidate; Human POST later`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_fx_remeasurement_pg.py`; `G-FX`, `PG-FX-CLOSE`.
- **SRS requirements (4):** `SRS-FX-012`, `SRS-FX-013`, `SRS-FX-015`, `SRS-FX-017`.
- **Exit acceptance:** K-IFRS monetary only, 금액 Snapshot·revaluation journal/세무정책 분리
- **v1.1 guard:** FX rate source and policy version approved; preserve original currency and functional currency, rule selection, snapshot, settlement/revaluation. Do not fabricate rates.

#### `S5-03` — Period Closing Gate·외화 결제·환차손익 | **NeX primary**

- **PR / Branch:** `NEX-s5_03` → `nurigitdev/2607_nex_platform` : `feat/eos/s5-03`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S5-02/S1-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/accounting_periods.py` ; `services/nex-eos/nex_eos/journals.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/period_closing.py` ; `services/nex-eos/nex_eos/fx_settlement.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql`.
- **API / Tool:** `FINANCE.PERIOD.CLOSE; settlement approved flow`; NSL `CREATE_DRAFT -> Human -> CREATE journal`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_period_close_fx_pg.py`; `G-FX`, `G-PERIOD`.
- **SRS requirements (3):** `SRS-FX-014`, `SRS-PER-003`, `SRS-PER-004`.
- **Exit acceptance:** OPEN 경합 일관성·closing-rate 및 미처리 UNKNOWN 차단
- **v1.1 guard:** FX rate source and policy version approved; preserve original currency and functional currency, rule selection, snapshot, settlement/revaluation. Do not fabricate rates.

#### `S5-04` — Journal Verify/Recon/GL 조회·오류 복구 | **NeX primary**

- **PR / Branch:** `NEX-s5_04` → `nurigitdev/2607_nex_platform` : `feat/eos/s5-04`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S4-04/S5-02`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/business_queries.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_post_write_verification.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/journal_read_api.py` ; `services/nex-eos/nex_eos/journal_reconciliation.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql`.
- **API / Tool:** `FINANCE.JOURNAL.GET/VERIFY/RECONCILE`; NSL `READ post-write verification + exact hashes`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_journal_verification.py`; `G-RECOVERY`, `PG-QUERY`.
- **SRS requirements (1):** `SRS-FX-020`.
- **Exit acceptance:** COMMITTED + VERIFY_FAILED 별도 경고, 재기표 금지

### G. Cost Source & Allocation (4 packets)

#### `S6-01` — POSTED GL SourcePool 적격성 | **NeX primary**

- **PR / Branch:** `NEX-s6_01` → `nurigitdev/2607_nex_platform` : `feat/eos/s6-01`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S4-03/S1-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/journals.py` ; `services/nex-eos/nex_eos/account_catalog.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/cost_source_pools.py` ; `services/nex-eos/nex_eos/cost_source_pool_api.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql`.
- **API / Tool:** `Cost source pool internal read admission`; NSL `READ eligible component; no manual GL duplication`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_cost_pool.py`; `G-ALLOCATION`, `PG-POOL`.
- **SRS requirements (6):** `SRS-ALC-001`, `SRS-ALC-002`, `SRS-ALC-003`, `SRS-ALC-010`, `SRS-ALC-011`, `SRS-ALC-012`.
- **Exit acceptance:** 비용계정만, 자산/AP/예수금·FX 구분, source unique + company

#### `S6-02` — Allocation Plan 릴리스·배부 정책 | **NeX primary**

- **PR / Branch:** `NEX-s6_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s6-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S6-01/S1-06`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/project_work_assignments.py` ; `services/nex-eos/nex_eos/project_memberships.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/allocation_plans.py` ; `services/nex-eos/nex_eos/allocation_plan_api.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql`.
- **API / Tool:** `Allocation plan approve/read v2`; NSL `WRITE CREATE/UPDATE only admitted; Human plan approval`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_allocation_plan.py`; `G-ALLOCATION`, `PG-POLICY`.
- **SRS requirements (0):** Shared infrastructure packet; no dedicated unique SRS ID in v1.0 (retained by intent).
- **Exit acceptance:** 업무실적→계획→인력매개→지정비율 원천/승인 hash

#### `S6-03` — Deterministic Allocation Batch·대사 | **NeX primary**

- **PR / Branch:** `NEX-s6_03` → `nurigitdev/2607_nex_platform` : `feat/eos/s6-03`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S6-02`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/business_transactions.py` ; `services/nex-eos/nex_eos/outbox_publication.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/cost_allocations.py` ; `services/nex-eos/nex_eos/allocation_reconciliation.py` ; `services/nex-eos/nex_eos/cost_allocation_api.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql`.
- **API / Tool:** `FINANCE.COST_ALLOCATION.RUN/VERIFY`; NSL `WRITE CREATE batch + READ VERIFY`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_allocation_pg.py`; `G-ALLOCATION`, `PG-CONSERVE`.
- **SRS requirements (6):** `SRS-ALC-006`, `SRS-ALC-007`, `SRS-ALC-008`, `SRS-ALC-009`, `SRS-ALC-013`, `SRS-ALC-014`.
- **Exit acceptance:** E=D+A+U 정확; 20경합 1 Batch; DIRECT/MANAGEMENT 배타

#### `S6-04` — D08 Payroll / D15 Purchase 최소 소스 어댑터 | **MyBee primary**

- **PR / Branch:** `MYB-s6_04` → `nurigitdev/2611_MyBee_Service` : `feat/mybee/s6-04`; merge to `main`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S6-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/allocation_plans.py` ; `services/nex-eos/nex_eos/journals.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/cost_source_intake.py` ; `services/nex-eos/nex_eos/cost_source_intake_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/integrations/payroll_source.py` ; `src/mybee_ax/integrations/purchasing_source.py` ; `tests/test_domain_cost_adapters.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql`.
- **API / Tool:** `D08/D15 source ingest → approved candidate v2`; NSL `NSL domain Skill invokes canonical EOS tools`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_mybee_domain_cost_pilots.py`; `G-ALLOCATION`, `G-PRIVACY`.
- **SRS requirements (2):** `SRS-ALC-004`, `SRS-ALC-015`.
- **Exit acceptance:** 급여 개인금액 차단, 구매 120/100/20 재고, FX gain 기본 공용 미귀속
- **v1.1 guard:** DECISION: remove old nex-eos/mybee_cost_source_adapters.py; domain D08/D15 adapters are MyBee-only; NeX owns generic source-pool/candidate intake contract and authorization.

### H. Budget & P&L (4 packets)

#### `S7-01` — D04 Budget SoR / D12 Project Budget Link | **NeX primary**

- **PR / Branch:** `NEX-s7_01` → `nurigitdev/2607_nex_platform` : `feat/eos/s7-01`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S1-05/S4-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/projects.py` ; `services/nex-eos/nex_eos/business_transactions.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/budgets.py` ; `services/nex-eos/nex_eos/project_budget_bindings.py` ; `services/nex-eos/nex_eos/budget_api.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2526_eos_project_budget_master.sql`.
- **API / Tool:** `Budget read/commit v2, D12 readonly link`; NSL `Governed Budget WRITE, Project READ`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_budget.py`; `G-BUDGET`, `PG-BUDGET`.
- **SRS requirements (0):** Shared infrastructure packet; no dedicated unique SRS ID in v1.0 (retained by intent).
- **Exit acceptance:** 예산 하나의 SoR, 승인 예산 고정/실적은 GL·Allocation 파생

#### `S7-02` — Project P&L Query/Projection·Watermark | **NeX primary**

- **PR / Branch:** `NEX-s7_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s7-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S6-03/S7-01`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/journals.py` ; `services/nex-eos/nex_eos/outbox_publication.py` ; `services/nex-eos/nex_eos/projects.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/project_pnl.py` ; `services/nex-eos/nex_eos/pnl_projector.py` ; `services/nex-eos/nex_eos/pnl_api.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/integrations/nex_pnl_client.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2527_eos_project_pnl_projection.sql`.
- **API / Tool:** `FINANCE.PROJECT_PNL.GET`; NSL `READ scoped P&L, no new monetary SoR`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_project_pnl.py`; `G-PNL`, `PG-PROJECTION`.
- **SRS requirements (8):** `SRS-FX-019`, `SRS-PNL-001`, `SRS-PNL-002`, `SRS-PNL-006`, `SRS-PNL-007`, `SRS-PNL-008`, `SRS-PNL-009`, `SRS-PNL-010`.
- **Exit acceptance:** POSTED actual만; 손익 미기표·지연·미배부 구분, as_of/watermarks

#### `S7-03` — Executive P&L 보안/소인원 역산 방지 | **NeX primary**

- **PR / Branch:** `NEX-s7_03` → `nurigitdev/2607_nex_platform` : `feat/eos/s7-03`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S7-02/S1-06`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/authorization.py` ; `services/nex-eos/nex_eos/voucher_access.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/pnl_privacy.py` ; `services/nex-eos/nex_eos/pnl_access.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `src/mybee_ax/domain/pnl_access_projections.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2527_eos_project_pnl_projection.sql`.
- **API / Tool:** `FINANCE.PROJECT_PNL.GET; FINANCE.NVT_PNL.GET`; NSL `READ classification EAC/OA scope`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_pnl_privacy.py`; `G-PRIVACY`, `PG-RLS`.
- **SRS requirements (6):** `SRS-ALC-005`, `SRS-ARCH-010`, `SRS-PNL-004`, `SRS-PNL-005`, `SRS-SEC-004`, `SRS-SEC-006`.
- **Exit acceptance:** PA 개인급여 금지, group/company aggregation·필터 차분 공격 차단

#### `S7-04` — NVT 롤업·Project 종결/미정산 검증 | **NeX primary**

- **PR / Branch:** `NEX-s7_04` → `nurigitdev/2607_nex_platform` : `feat/eos/s7-04`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S7-02/S5-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-eos/nex_eos/projects.py` ; `services/nex-eos/nex_eos/project_operations.py`.
- **NeX expected changes (PROPOSED):** `services/nex-eos/nex_eos/project_close_guards.py` ; `services/nex-eos/nex_eos/nvt_pnl_rollup.py`.
- **NeX-owned Migration (PROPOSED / NOT APPLIED):** `database/nex-eos/migrations/2527_eos_project_pnl_projection.sql`.
- **API / Tool:** `FINANCE.NVT_PNL.GET; project close check`; NSL `READ authoritative receipts + governed close`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_eos_mybee_project_close.py`; `G-PNL`, `G-PROJECT`.
- **SRS requirements (2):** `SRS-PNL-003`, `SRS-PRJ-007`.
- **Exit acceptance:** 후손 1회 합산; 미기표·미배부·미결재·미FX정산 종결 차단

### I. Tool Bindings & Release (5 packets)

#### `S8-01` — NSL Tool JSON Schema·Registry·Skill Pack | **MyBee primary**

- **PR / Branch:** `MYB-s8_01` → `nurigitdev/2611_MyBee_Service` : `feat/mybee/s8-01`; merge to `main`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S0-03/S4-03/S6-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `examples/voucher_draft_validation/tools_write.json [NSL repo]` ; `contracts/schemas/service/nex_eos/create_voucher_draft_command.v1.schema.json [NeX repo]`.
- **NeX expected changes (PROPOSED):** `contracts/schemas/service/nex_eos/eos_voucher_candidate_create_v2.schema.json` ; `contracts/schemas/service/nex_eos/eos_accounting_posting_v2.schema.json` ; `contracts/schemas/service/nex_eos/eos_cost_allocation_v2.schema.json` ; `contracts/schemas/service/nex_eos/eos_fx_rate_snapshot_v2.schema.json` ; `contracts/schemas/service/nex_eos/eos_project_pnl_query_v2.schema.json` ; `contracts/openapi/nex-eos.openapi.yaml` ; `services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py`.
- **MyBee consumer/domain file candidates (PROPOSED):** `skills/d04_accounting/manifest.json` ; `skills/d12_project/manifest.json` ; `src/mybee_ax/integrations/nex_tool_bindings.py`.
- **API / Tool:** `All FINANCE/PROJECT v2 operations, existing v1 untouched`; NSL `NSL 0.2/0.2.1 admitted kinds only, CREATE not POST`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_mybee_nsl_contracts.py`; `G-ARCH`, `G-NSL`.
- **SRS requirements (0):** Shared infrastructure packet; no dedicated unique SRS ID in v1.0 (retained by intent).
- **Exit acceptance:** 코어 컴파일러 수정 0, canonical contract compile/negative PASS
- **v1.1 guard:** DECISION: canonical JSON Schemas/OpenAPI/Tool registry belong to NeX; domain Skill Pack and FL->Tool bindings belong to MyBee. Separate linked provider/consumer PRs.

#### `S8-02` — AE Binding·NSL Postwrite Verify/Recon | **NeX primary**

- **PR / Branch:** `NEX-s8_02` → `nurigitdev/2607_nex_platform` : `feat/eos/s8-02`; merge to `master`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S8-01/S5-04`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_reconciliation.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_post_write_verification.py`.
- **NeX expected changes (PROPOSED):** `services/nex-ae-api/nex_ae_api/nsl_eos_journal_execution.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_journal_reconciliation.py` ; `services/nex-ae-api/nex_ae_api/nsl_eos_journal_verification.py`.
- **API / Tool:** `AE-to-EOS v2 tool binding`; NSL `WRITE CREATE, typed UNKNOWN, READ_AFTER_WRITE_STRONG`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_nex_ae_mybee_nsl_eos_integration.py`; `G-NSL`, `G-RECOVERY`.
- **SRS requirements (1):** `SRS-COM-002`.
- **Exit acceptance:** 고정 wheel/hash, 검증 실패 뒤 이중 Posting 0

#### `S8-03` — Golden E2E: 승인 USD 공용전표→손익 | **MyBee primary**

- **PR / Branch:** `MYB-s8_03` → `nurigitdev/2611_MyBee_Service` : `feat/mybee/s8-03`; merge to `main`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S8-02/S7-03`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `tests/test_nex_ae_eos_p8_s66_golden_a_commit_journey.py` ; `tests/test_nex_eos_p8_s73_approval_transition.py`.
- **NeX expected changes (PROPOSED):** `tests/test_nex_eos_mybee_public_journey_provider.py` ; `tests/fixtures/mybee_fx_shared_purchase.json`.
- **MyBee consumer/domain file candidates (PROPOSED):** `tests/e2e/test_approved_usd_shared_purchase.py`.
- **API / Tool:** `E2E-D04D12-FX-01`; NSL `NSL Candidate/Journal/Allocation/P&L chain`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_mybee_d04d12_fx_e2e.py`; `G-E2E`, `G-FX`.
- **SRS requirements (0):** Shared infrastructure packet; no dedicated unique SRS ID in v1.0 (retained by intent).
- **Exit acceptance:** USD10k×1350.20=KRW13,502,000; 40/60 split, no duplicate
- **v1.1 guard:** MyBee owns business E2E; NeX owns financial posting and provider Golden Journey assertions; no runtime state forged by test runner.

#### `S8-04` — Payroll·Inventory·FX settlement/close E2E | **MyBee primary**

- **PR / Branch:** `MYB-s8_04` → `nurigitdev/2611_MyBee_Service` : `feat/mybee/s8-04`; merge to `main`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S8-03/S5-03/S6-04`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `docs/mybee_d04d12/traceability/requirements.json`.
- **NeX expected changes (PROPOSED):** `tests/test_nex_eos_mybee_domain_compatibility.py` ; `tests/fixtures/mybee_payroll_purchase_fx.json`.
- **MyBee consumer/domain file candidates (PROPOSED):** `tests/e2e/test_payroll_purchase_fx_close.py`.
- **API / Tool:** `E2E-D04D12-01..09 and FX-02..03`; NSL `All admitted NSL provider-independent Tool profiles`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_mybee_d04d12_domain_e2e.py`; `G-E2E`, `G-PRIVACY`.
- **SRS requirements (0):** Shared infrastructure packet; no dedicated unique SRS ID in v1.0 (retained by intent).
- **Exit acceptance:** 급여 개인정보/재고/환차손익/외환결산/문서한도 동시 검증
- **v1.1 guard:** MyBee owns payroll/purchase/FX scenario inputs; NeX owns API correctness and atomic financial facts. Independent suites required.

#### `S8-05` — Full Regression·Signoffs·Controlled Release Closure | **MyBee primary**

- **PR / Branch:** `MYB-s8_05` → `nurigitdev/2611_MyBee_Service` : `feat/mybee/s8-05`; merge to `main`. Status `PLANNED_NOT_EXECUTED`.
- **Prerequisite:** `S8-04`; additional cross-repo gates when canonical provider/consumer both changed.
- **Existing code/reference (NeX):** `scripts/quality/run_quality_gate.sh` ; `scripts/db/run_migrations.py`.
- **NeX expected changes (PROPOSED):** `docs/mybee_d04d12/closure/nex_provider_release_evidence.json` ; `docs/mybee_d04d12/closure/evidence_manifest.json`.
- **MyBee consumer/domain file candidates (PROPOSED):** `releases/phase1/compatibility.lock.json` ; `releases/phase1/mybee_release_evidence.json`.
- **API / Tool:** `Full API/PG/E2E & deployment enable switch`; NSL `NSL wheel admissibility + rollback gates`. Provider owns EOS contract and semantic Tool; MyBee owns domain binding.
- **pytest / Gate:** `tests/test_mybee_d04d12_release_closure.py`; `G-RELEASE`, `G-SRC-PDF`.
- **SRS requirements (0):** Shared infrastructure packet; no dedicated unique SRS ID in v1.0 (retained by intent).
- **Exit acceptance:** 116 SRS + 18 ACID + 12 E2E 100%, EOS ≥96/94, 12 gate evidence
- **v1.1 guard:** Two independently tagged releases. Provider passes acceptance first; consumer compatibility lock and end-user E2E second; rollback never deletes posted finance data.

## 5. 13 new MyBee domain packets — separate `main` delivery

The new application repository is not yet created. Paths below are planned scaffolding, not existing files. They are **additional** consumer-domain work and do not renumber the 37 EOS packet IDs or invent new EOS SRS requirements.

### `MB0-01` — MyBee Service repo Bootstrap / lint / pytest / CI

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb0-01`, PR `MYB-mb0-01` → `main` (after repo creation).
- **Required NeX provider packets:** S0 baseline / new repository readiness.
- **PROPOSED files:** `pyproject.toml`; `src/mybee_ax/__init__.py`; `.github/workflows/ci.yml`; `.github/CODEOWNERS`; `tests/test_bootstrap.py`; `README.md`.
- **Acceptance:** Initialize new repo, no copy of nex-eos sources, CODEOWNERS and branch policy checks
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB0-02` — Pinned compatibility / consumer contract harness

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb0-02`, PR `MYB-mb0-02` → `main` (after repo creation).
- **Required NeX provider packets:** `S0-01`, `S0-03`.
- **PROPOSED files:** `compatibility/platform.lock.json`; `compatibility/check_lock.py`; `tests/contracts/test_nex_api_compatibility.py`.
- **Acceptance:** Record EOS OpenAPI SHA, canonical tool versions, NSL wheel digest, baseline PR checks
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB1-01` — FL code catalog + revisioned release

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb1-01`, PR `MYB-mb1-01` → `main` (after repo creation).
- **Required NeX provider packets:** `S1-05`.
- **PROPOSED files:** `catalog/work_codes/catalog.v1.json`; `catalog/work_codes/schema.json`; `src/mybee_ax/domain/work_codes.py`; `tests/test_work_code_registry.py`.
- **Acceptance:** Catalog FLxxxxxxx, domain grouping, owner, version, signed mapping; no platform engine duplication
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB1-02` — D12 Project templates / five required FL codes

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb1-02`, PR `MYB-mb1-02` → `main` (after repo creation).
- **Required NeX provider packets:** `S1-05`.
- **PROPOSED files:** `templates/d12/required_five.json`; `src/mybee_ax/domain/project_templates.py`; `tests/test_d12_mandatory_codes.py`.
- **Acceptance:** Enforce mandated D12 5 through EOS readiness API and negative fixtures
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB1-03` — K-IFRS COA Seed / FX policy input bundle

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb1-03`, PR `MYB-mb1-03` → `main` (after repo creation).
- **Required NeX provider packets:** `S1-02`, `S1-04`.
- **PROPOSED files:** `config/account_catalog/approved_seed_manifest.json`; `config/fx/approved_rate_source_policy.json`; `tests/test_finance_seed_lineage.py`.
- **Acceptance:** Approved source/provenance/version; EOS canonical policy admission; no fabricated legal rate
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB1-04` — Grade/Man-Day planning policy + protected costs

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb1-04`, PR `MYB-mb1-04` → `main` (after repo creation).
- **Required NeX provider packets:** `S1-06`.
- **PROPOSED files:** `src/mybee_ax/domain/workforce_planning.py`; `tests/test_grade_man_day_privacy.py`.
- **Acceptance:** Company policy, aggregate-only views, no private payroll leak
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB2-01` — Draft/품의 forms / approval journey

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb2-01`, PR `MYB-mb2-01` → `main` (after repo creation).
- **Required NeX provider packets:** `S2-01`, `S2-02`.
- **PROPOSED files:** `src/mybee_ax/domain/documents.py`; `src/mybee_ax/integrations/nex_business_approval_client.py`; `tests/test_document_signoff.py`.
- **Acceptance:** Document revisions, amount cap, attachments, business approval steps, WC/EOS reuse
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB3-01` — Voucher candidate domain adapter / evidence binding

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb3-01`, PR `MYB-mb3-01` → `main` (after repo creation).
- **Required NeX provider packets:** `S3-01`, `S3-02`.
- **PROPOSED files:** `src/mybee_ax/integrations/nex_voucher_candidate_client.py`; `tests/test_voucher_candidate_consumer.py`.
- **Acceptance:** MyBee work code and document to EOS Candidate v2; no direct GL write
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB6-01` — D08 Payroll resource adapter

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb6-01`, PR `MYB-mb6-01` → `main` (after repo creation).
- **Required NeX provider packets:** `S6-01`, `S6-03`, `S6-04`.
- **PROPOSED files:** `src/mybee_ax/integrations/payroll_source.py`; `tests/test_payroll_aggregate_adapter.py`.
- **Acceptance:** Monthly group payroll source + project allocation evidence, privacy controls
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB6-02` — D15 Purchasing resource adapter

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb6-02`, PR `MYB-mb6-02` → `main` (after repo creation).
- **Required NeX provider packets:** `S6-01`, `S6-03`, `S6-04`.
- **PROPOSED files:** `src/mybee_ax/integrations/purchasing_source.py`; `tests/test_shared_purchase_adapter.py`.
- **Acceptance:** Shared PO, receipt, inventory surplus and approved posting request
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB7-01` — Project/NVT executive P&L workspace

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb7-01`, PR `MYB-mb7-01` → `main` (after repo creation).
- **Required NeX provider packets:** `S7-02`, `S7-03`.
- **PROPOSED files:** `apps/mybee-web/src/features/projectPnl/`; `src/mybee_ax/integrations/nex_pnl_client.py`; `tests/test_pnl_privacy_consumer.py`.
- **Acceptance:** Read-only EOS P&L, watermark, unposted/unallocated vs booked signals
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB8-01` — MyBee D04/D12 certified Skill Pack + PA orchestration

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb8-01`, PR `MYB-mb8-01` → `main` (after repo creation).
- **Required NeX provider packets:** `S8-01`, `S8-02`.
- **PROPOSED files:** `skills/d04_accounting/manifest.json`; `skills/d12_project/manifest.json`; `src/mybee_ax/integrations/nex_tool_bindings.py`; `tests/test_mybee_skill_admission.py`.
- **Acceptance:** Binding to exact admitted Tool contracts/NSP versions; no private runtime changes
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

### `MB8-02` — Multi-repo business E2E / compatibility release

- **Repo / PR:** `nurigitdev/2611_MyBee_Service`, branch `feat/mybee/mb8-02`, PR `MYB-mb8-02` → `main` (after repo creation).
- **Required NeX provider packets:** `S8-03`, `S8-04`, `S8-05`.
- **PROPOSED files:** `tests/e2e/test_approved_usd_shared_purchase.py`; `tests/e2e/test_payroll_purchase_fx_close.py`; `releases/phase1/compatibility.lock.json`; `releases/phase1/consumer_acceptance.json`.
- **Acceptance:** Cross-repo public API journey; signed dependency manifest, sign-off and rollout
- **Required CI:** MyBee pytest/contract lock/negative scope & privacy tests, G-BOUNDARY import scanner; provider PG acceptance is still NeX-owned.

## 6. Cross-repo implementation chronology (no mutable branch dependency)

| Wave | Provider PR (NeX) | Consumer PR (MyBee) | Merge/order / evidence |
|---|---|---|---|
| 0. Baselines | S0-01..03, Golden A regression | MB0-01, MB0-02 | Blueprint pinned; NeX master hash; new MyBee main CI; exact contract lock |
| 1. Master & FX | S1-01..06 | MB1-01..04 | NeX company/COA/FX/WorkCode API acceptance precedes MyBee policy seed promotion; accountant seed approval |
| 2. Business approval | S2-01..04 | MB2-01 | NeX document proof + OA/WC guarded scope API, then MyBee forms; double spend reject |
| 3. Candidate v2 | S3-01..03 | MB3-01 | NeX Candidate v2 contract/negative tests then MyBee mapper; P8 v1 unchanged |
| 4. Atomic posting | S4-01..04 | Consumer mocks pinned; no MyBee GL | NeX protected PG ACID & accountant proof+SoD+replay PASS before MyBee enabled |
| 5. FX & close | S5-01..04 | MB1-03 source policies updated only if approved | NeX monetary/nonmonetary FX test, period lock, reversal and provenance |
| 6. Allocation | S6-01..04N | S6-04M, MB6-01, MB6-02 | Provider neutral SourcePool intake+APIs before MyBee payroll/purchase; balance/conservation |
| 7. P&L | S7-01..04 | MB7-01 | Provider budget/P&L/scoped read + suppressed salary before consumer UX |
| 8. Skills & launch | S8-01N, S8-02 provider bindings, S8-03/04 provider journey | S8-01M, MB8-01, S8-03/04 consumer journey, MB8-02 | Wheel digest and code schema locked; full PG+E2E; independent tags; no shared master merge |

### 6.1 Review/merge checklist for *every* linked pair

- Provider PR must include canonical Schema/OpenAPI + positive/negative fixtures, backward compatibility diff, exact named endpoint/Tool and OA scope; publish an immutable RC digest and test evidence before consumer asserts compatibility.
- Consumer PR uses exact RC digest/contract hash and tests both success/denial, stale approval proof, cross-company, idempotency-conflict, financial balance and privacy when applicable.
- If Platform provider PR is merged but MyBee consumer is not, remain backward compatible and disabled/guarded. If MyBee consumer PR is ready but provider RC failed, **do not** release it.
- MyBee business/data payload must not silently redefine GL Posting, Project identity or salary visibility; independent finance/security approvals still required.
- A release compatibility file must record Platform Git SHA+image digest, EOS OpenAPI schema hash, canonical Tool contract version/hash, NSL admitted wheel version+SHA, FL catalog release, MyBee Git SHA+image digest, seed/FX policy version+hash, required gates and timestamps. Never use floating `master`/`main` as release dependency.

### 6.2 Suggested `compatibility.lock.json` shape (illustrative; values are placeholders)

```json
{
  "schema_version": "mybee.platform_compatibility_lock.v1",
  "mybee_release": "<exact-semver-and-git-sha>",
  "nex_platform": {
    "git_sha": "<40-hex>",
    "image_digest": "sha256:<64-hex>"
  },
  "eos_api": {
    "openapi_version": "<pinned-version>",
    "schema_sha256": "sha256:<64-hex>"
  },
  "nsl": {
    "version": "<exact admitted version>",
    "wheel_sha256": "sha256:<64-hex>"
  },
  "canonical_tool_registry": {
    "version": "<version>",
    "sha256": "sha256:<64-hex>"
  },
  "mybee_work_codes": {
    "release": "<version>",
    "sha256": "sha256:<64-hex>"
  },
  "account_catalog_seed": {
    "approval_ref": "<finance-approved-ref>",
    "sha256": "sha256:<64-hex>"
  },
  "fx_policy": {
    "approval_ref": "<finance-approved-ref>",
    "sha256": "sha256:<64-hex>"
  },
  "acceptance_evidence": {
    "golden_a": "<sha-or-evidence-ref>",
    "pg_acid": "<sha-or-evidence-ref>",
    "e2e": "<sha-or-evidence-ref>"
  }
}
```

**Important:** Replace all placeholders using signed artifacts, not the observed HEAD values from planning. Lock schema is not a claim these versions have been built.

## 7. CI Gate responsibility and protected business acceptance

| Gate | Owner / execution | Requirements | Failure action |
|---|---|---|---|
| `G-ARCH` | NeX and MyBee | Frozen diff=0; no cross DB access/import; source/contract SHA lock | Block PR |
| `G-SRC-PDF` | Blueprint/Domain Owner | D04 v1.9 / D12 v2.8 PDF page-by-page verified, tagged line mapping, finance signoff | Block Release; optionally block code depending on ambiguity |
| `G-V1` | NeX | P8/Golden A legacy voucher DRAFT schema and adapter contract unchanged | Block provider PR |
| `G-NSL` | NeX AE/NSL + MyBee | Approved wheel/version/digest, Tool contract, trust policy; no new POST OperationKind | Block skill/WRITE activation |
| `G-DOC / G-HUMAN` | NeX EOS/WC/OA | Document proof, company approval scope, accountant SoD + stale revoke denial | Block financial PR |
| `G-GL-ACID` | NeX EOS | One PostgreSQL transaction for journal, state, allowance, idem, outbox | Block financial release |
| `G-FX` | NeX EOS + Finance | Approved spot/매매기준율 source and snapshot, closing/settlement remeasurement | Block FX posting release |
| `G-ALLOCATION / G-PNL` | NeX EOS | Source conservation, NO DOUBLE COUNT, protected P&L watermark, NVT totals | Block finance release |
| `G-PG` | NeX | Real protected test-DB PostgreSQL, 18 fault/concurrency cases; not SQLite/dry-run | Block provider release |
| `G-CONSUMER / G-BOUNDARY` | MyBee | Pinned APIs and schemas, negative fixtures, no direct EOS DB or NSL internals | Block MyBee PR |
| `G-CROSSREPO-E2E` | Both | 12 business journeys via public API/browser, no handcrafted runtime state | Block joint compatibility certification |
| `G-RELEASE` | Both independent | Owner review, signature, financial/privacy signoff, manifest tag, rollback/fixforward | No deploy/activation |

**Actual NeX Full Gate from `docs/development_process.md`:** Slice/Checkpoint statement ≥95%, branch ≥94%; Full compatibility statement ≥95%, branch ≥85%, accompanied by previous successful Full coverage delta review. Do **not** substitute other project-specific 96/94 thresholds without approved quality-policy amendment.

### 7.1 PostgreSQL fault and E2E acceptance ownership (preserved IDs)

The **18 original** `fault_acceptance` entries in the v1.0 JSON retain their ID, test hint, and packet owner. NeX runs these with protected EOS test PostgreSQL identity; actual execution status remains NOT_STARTED. The **12 original** `e2e_acceptance` entries retain IDs; MyBee owns business scenario orchestration, NeX owns provider financial assertions and result verification. Full details and exact 1:1 ID mappings are embedded in `..._Repository_Ownership_Matrix.json`.

| Scenario / critical fault | NeX provider asserted fact | MyBee asserted fact |
|---|---|---|
| Approved USD shared purchase | Exact FX source snapshot, human accounting approval, single atomic POSTED Journal, 40/60 expense attribution | Business proposal and approval UX, two project lines, currency and source ledger references |
| Duplicate/ACK lost after posting | Same BusinessOperationId and immutable Journal once; reconcile UNKNOWN, no unsafe retry | UX displays recovery state, no second user-induced posting |
| Shared payroll | Aggregate payroll posted, allocation total conservation, protected labor source | Private per-person salary never exposed to PA/ordinary PM |
| Received vs unused inventory | Cash/stock/expense recognition correctly separated, no 20-unit surplus expense until eligible | Purchase receipt + lot surplus manifest and cost source line mapping |
| Foreign-currency close | Monetary-only remeasurement, approved closing rates, realized/unrealized FX classified | Policy selection and displayed ledger currency provenance, no guessed rate |
| Project/NVT P&L | Direct or management allocation exactly once, watermark, unposted vs booked | Executive UI safe aggregate/differencing suppression and disclosure labels |

**Golden Journey runner rule:** only pre-prepare canonical master/evidence fixtures. Once request enters through UI/public API, runner may poll/read/assert/restart/cleanup but must not directly create WC work transitions, EOS/outbox financial mutations, NSL runtime jobs or WA result state. Use existing `scripts/quality/run_golden_journey_transition_audit.py`.

## 8. SRS requirement-by-repository mapping and migration integrity

Every one of the original 116 SRS IDs is assigned to exactly one original `S*-**` primary packet and unchanged relative to v1.0. The v1.1 traceability JSON adds `v1_1_primary_repository`, `v1_1_platform_provider_repository`, `v1_1_mybee_consumer_repository`, proposed owner-side source paths and consumer contract gate. The supplemental `MB*` packets reference existing EOS SRS needs and may add **MyBee domain SRS IDs separately** later, but never silently alter EOS SRS v1.0.

### 8.1 Primary packet counts by stage

| Stage | Packet IDs | NeX primary | MyBee primary |
|---|---|---:|---:|
| S0 | `S0-01`–`S0-03` | 3 | 0 |
| S1 | `S1-01`–`S1-06` | 6 | 0 |
| S2 | `S2-01`–`S2-04` | 4 | 0 |
| S3 | `S3-01`–`S3-03` | 3 | 0 |
| S4 | `S4-01`–`S4-04` | 4 | 0 |
| S5 | `S5-01`–`S5-04` | 4 | 0 |
| S6 | `S6-01`–`S6-04` | 3 | 1 |
| S7 | `S7-01`–`S7-04` | 4 | 0 |
| S8 | `S8-01`–`S8-05` | 1 | 4 |

### 8.2 Migration ownership (PROPOSED / conflict check before each slice)

| Version | NeX-owned planned SQL | Main packet(s) | MyBee DDL? |
|---|---|---|---|
| 2516 | `database/nex-eos/migrations/2516_eos_legal_entity_project_binding.sql` | `S1-01` | **Never** |
| 2517 | `database/nex-eos/migrations/2517_eos_account_catalog_accounting_period.sql` | `S1-02`, `S1-03` | **Never** |
| 2518 | `database/nex-eos/migrations/2518_eos_fx_rate_policy_snapshot.sql` | `S1-04` | **Never** |
| 2519 | `database/nex-eos/migrations/2519_eos_project_work_code_readiness.sql` | `S1-05`, `S1-06` | **Never** |
| 2520 | `database/nex-eos/migrations/2520_eos_document_approval_envelope.sql` | `S2-01`, `S2-04` | **Never** |
| 2521 | `database/nex-eos/migrations/2521_eos_scoped_approval_case_v2.sql` | `S2-02`, `S2-03` | **Never** |
| 2522 | `database/nex-eos/migrations/2522_eos_voucher_candidate_v2.sql` | `S3-01`, `S3-02`, `S3-03` | **Never** |
| 2523 | `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql` | `S4-01`, `S4-02`, `S4-03`, `S4-04` | **Never** |
| 2524 | `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql` | `S5-01`, `S5-02`, `S5-03`, `S5-04` | **Never** |
| 2525 | `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql` | `S6-01`, `S6-02`, `S6-03`, `S6-04` | **Never** |
| 2526 | `database/nex-eos/migrations/2526_eos_project_budget_master.sql` | `S7-01` | **Never** |
| 2527 | `database/nex-eos/migrations/2527_eos_project_pnl_projection.sql` | `S7-02`, `S7-03`, `S7-04` | **Never** |

Before actual migration creation, run migration listing + DB test-profile dry-run, then guarded PostgreSQL execution with explicit `NEX_EOS_TEST_DATABASE_URL`; never copy MyBee schema into EOS. All 12 are **planned filenames, not applied migrations**. MyBee DB must have an independent schema/migration namespace for domain-only records.

### 8.3 SRS coverage integrity check

```text
original_isp_packets == current_isp_packets: 37 / 37, IDs unchanged
original_srs_requirements == current_srs_requirements: 116 / 116, IDs and primary_packet_id unchanged
owner cardinality: NeX=32, MyBee=5, one primary owner per original packet
supplemental MyBee work: 13 distinct MB packet IDs
fault_acceptance: 18 / 18 IDs and expectations unchanged
e2e_acceptance: 12 / 12 IDs and expectations unchanged
NeX migration versions: 2516–2527 contiguous, PROPOSED_NOT_APPLIED
```

## 9. Codex handoff — first executable batches

| Batch | Scope | Stop condition |
|---|---|---|
| B0 | NeX `S0-01/S0-02/S0-03` snapshot, MyBee `MB0-01/02` repository bootstrap and lock schema | No branch merge if Frozen baseline mismatch or new repo/CI not verified |
| B1 | NeX `S1-01..S1-06`, MyBee `MB1-01..MB1-04` | Release only approved FX policy and adopted COA; reject WorkCode readiness bypass |
| B2 | NeX `S2-01..S3-03`, MyBee `MB2-01/MB3-01` | Document proof and accountant authorization require separate valid human evidence |
| B3 | NeX `S4-01..S5-04` | **Hard barrier**: journal ACID+idempotency+unknown outcome+FX/period PG gate PASS |
| B4 | NeX `S6-01..S7-04`, MyBee `S6-04/MB6-01/02/MB7-01` | Allocation conservation, salary privacy and P&L watermark gated |
| B5 | NeX `S8-01N/S8-02`, MyBee `S8-01M/MB8-*` and `S8-03..05` | Cross repo 12 E2E + Golden A v1 + release signatures + compatibility lock |

**Recommended first Codex prompt (copyable; no implicit write authorization):**

```text
Implement only S0-01/S0-02/S0-03 in nurigitdev/2607_nex_platform,
and propose the linked MyBee MB0-01/MB0-02 bootstrap PR plan separately.
Read the v1.1 implementation plan, v1.0 SRS, v1.0 RBG PAD and the Frozen v2.1 Closure.
Refresh master HEAD, migration head, git status, relevant schemas and baseline test paths.
Do not modify Frozen semantics, production secrets, NSL language/core, v1 P8/Golden A,
or create EOS Posting/GL migrations in this first batch.
Record commands, results, source hashes, v1 compatibility evidence, reviewed PR files.
Do not claim tests passed without executing them; do not create MyBee repo implicitly.
```

## 10. Approval/closure conditions and unresolved items

**Ready for staged Codex implementation planning**, **not** a claim of readiness for production activation. The following items require owner sign-off:

- [ ] Create MyBee Service repository + CODEOWNERS/main/rulesets with verified effective review/required-status checks.
- [ ] D04 v1.9 and D12 v2.8 original PDF text+tables page-level source validation and MyBee domain owner acceptance.
- [ ] Finance accepts K-IFRS adopted COA seed and market base rate/closing FX source/policy and rounding+tax separation.
- [ ] OA security confirms company-scope accountant role, actual Scope and SoD negative tests; no synthetic Project for company document.
- [ ] NeX provider v2 API and Tool contract version/index/negative fixture review; admitted wheel digest established.
- [ ] NeX PostgreSQL `G-GL-ACID` and 18 fault test cases pass under test profile; Golden A P8 v1 passes.
- [ ] MyBee consumer 12 business E2E cases complete against signed platform artifacts without runtime-state fabrication.
- [ ] Independent platform + MyBee release tags and compatibility.lock inspected and signed; operational rollback documented.

**Change control:** If v1.1 owner classification conflicts with an approved v1.0 PAD aggregate boundary, the frozen NeX Architecture / EOS Business SoR wins and a controlled PAD amendment is required; do not fix an architectural conflict by moving tables to the MyBee service or by forking NSL/EOS code.

---

## Appendix A. Input lineage / SHA-256

- `MyBee_D04_D12_EOS_Implementation_Slice_Plan_v1.0.md` — `6e941c58000a9b82d480d66fff504a74c070a0d2b59609f86f540e5a7defabbb`
- `MyBee_D04_D12_EOS_Implementation_Traceability_v1.0.json` — `4537d2a657fbba4e68782f5fd758305e5589f68ad16a57e05d5fe5133748e747`
- `NeX_MyBee_Repo_PAD_v1.0.md` — `c912b3e26d02015afd17f164e58e9a8821b98c8d1e1e8bbdf5ec08085a9e80f0`
- `NeX_MyBee_Repository_Ownership_Matrix_v1.0.json` — `0c6acf7ddaed413e8a0e43f616a4dc39031312fe4304f965640501845d008aff`
- `MyBee_D04_D12_EOS_SRS_v1.0.md` — `7facf0620ce5e8b9d14c4a0c4895e6a2fb55e67edbe3578a6eb2536c661616fe`

## Appendix B. Machine-readable outputs

The v1.1 companion JSON includes complete 37 packet definitions, 13 MyBee new packets, all 116 SRS mappings, 18 PostgreSQL and 12 E2E test entries, twelve proposed EOS migration paths, source commit observations and PR/gate ownership. Validate JSON ID cardinality and ZIP checksum before distributing. No GitHub/production data mutation was performed.

