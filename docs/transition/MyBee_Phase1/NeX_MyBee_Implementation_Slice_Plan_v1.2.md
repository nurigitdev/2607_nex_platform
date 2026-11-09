# NeX–MyBee D04/D12 EOS Implementation Slice Plan v1.2 — Phase-1 In-Repository Execution Re-baseline

**Document ID:** `NEX-MYBEE-D04D12-EOS-ISP-P1-INREPO-20261109-V1.2`
**Date / timezone:** 2026-11-09, Asia/Seoul
**Status:** `IMPLEMENTATION PLANNING BASELINE — CODE NOT MODIFIED / GATES NOT EXECUTED`
**Authority:** NeX Agent/Platform v2.1 Frozen + NSL admitted contracts > EOS D04/D12 PAD/SRS > Phase-1 In-Repository ADR v1.0 > this execution-order rebaseline.
**Supersedes:** ISP v1.1 only for physical repository, proposed file placement, PR chronology and M1/M2 execution gating. Does NOT change source SRS, EOS transaction ownership or 37 original packet IDs.
**Git target:** `nurigitdev/2607_nex_platform` `master`; no long-lived feature branch, no EOS extraction before Phase-1.

> **Critical status discipline:** In this document `EXISTING` means the repository file was found in the prior source audit and confirmed against the unchanged HEAD where applicable; `PROPOSED` is a future Codex target, not an existing artifact. `PASS` appears only in future acceptance criteria, not as a result. No GitHub PR, migration, actual PostgreSQL test or production release has been executed by this planning step.

## 0. One-page decision and preservation ledger

**We stop debating repository extraction until Phase-1 evidence exists.** For Phase-1, EOS remains an independent `nex-eos` service inside the NeX Platform monorepo; MyBee D04/D12 domain catalog, policy, approved source manifests and Skill Packs are in `domains/mybee/`, and the public-API E2E sits under `tests/mybee_phase1/`. Each short-lived PR goes to the existing NeX `master`. No MyBee second ledger; no cross-service private ORM import; no private EOS DB connection from MyBee domain code.

| Preserved item | Count / ruling |
|---|---|
| Original S0–S8 packets | 37/37 — identifiers and full acceptance remain |
| SRS requirement IDs | 116/116 — original owner packet preserved |
| Supplemental MB domain tasks | 13/13 — rehost into monorepo, not 13 new repos |
| PostgreSQL fault/concurrency cases | 18/18 — `T-ACID-01..18` |
| Existing E2E cases | 12/12 — `E2E-D04D12-FX-01..03`, `E2E-D04D12-01..09` |
| Candidate EOS migrations | 2516..2527, 12 — not applied |
| P8/Golden A v1 | Unchanged; exact v1 draft/approval/NSL regression required |
| FX accounting | Phase-1 P0, mandatory for M2; approved FX snapshot used already in M1 USD scenario |
| EOS extraction | Deferred, review after M2; extraction itself not Phase-1 completion condition |

### 0.1 Git baseline (read-only verified)

| Source | Branch | Last verified commit | Role |
|---|---|---|---|
| NeX master | `master` | `5e64fb1f6b9af2198797d1bcdbc82e577b098fbe` | Implementation SoR |
| NSL master | `master` | `f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4` | Admitted NSL source; no code edit proposed |
| MyBee Blueprint main | `main` | `948b50fd43fc4e0f0d3f40ffd6335871ec741559` | Read-only business specification reference |

The Blueprint repository was accessible at the above commit. D04 v1.9 / D12 v2.8 source PDF and DOCX filenames were verified, but PDF **page-by-page semantic sign-off is still open** (`G-SRC-PDF`). Before any Codex packet: re-read `git status --short --branch`, refresh SHA and check EOS migration numbering. Existing EOS migration end at `2515` in the verified tree; `2516` onward is only a *proposal*.

### 0.2 Version lineage and explicit overrides

| Precedent | Keep | Override in v1.2 |
|---|---|---|
| EOS D04/D12 PAD v1.0 | EOS Aggregate/DB SoR; ApprovedDocument, scoped approval, journal posting and allocation | None |
| EOS SRS v1.0 | 116 functional requirements, FX/approval, state/negative/PG conditions | None |
| ISP v1.0 | 37 Codex packets, tests, 18/12 acceptance | Reorder to reach real PA E2E M1 earlier |
| ISP v1.1 — Repository Ownership | Logical owner labels and provider/consumer contract checks | **Physical repo = NeX monorepo for all 37 + 13 MB tasks**; cross-repo PR not mandatory |
| Repository Boundary PAD v1.0 | Domain roles, no duplicate GL, modular API contract | Physical multi-repo split **deferred for Phase-1** by later ADR |
| In-Repository Deferred EOS ADR v1.0 | 18 ADRs, M1/M2, deferred extraction Gate | **Authoritative for Phase-1**; no change |

## 1. Architecture ownership, source roots and import rules

```text
NeX monorepo / master (existing repository)
├── services/nex-ae-api/nex_ae_api/       EXISTING: IA/PA/NSL → EOS adapters
├── services/nex-oa/nex_oa/               EXISTING: identity / OA policy decision
├── services/nex-wc/nex_wc/               EXISTING: Work/Claim/Human Approval
├── services/nex-wa/nex_wa/               EXISTING: work evidence/artifacts
├── services/nex-eos/nex_eos/             EXISTING: only EOS Business SoR, extend
├── database/nex-eos/migrations/          EXISTING 2500–2515; PROPOSE 2516–2527
├── contracts/openapi/nex-eos.openapi.yaml EXISTING: additive v2 API
├── contracts/schemas/service/nex_eos/   EXISTING root; PROPOSE v2 schemas
├── domains/mybee/                       PROPOSED: FL catalog, D04/D12 templates,
│                                         domain adapters, signed Skill Pack,
│                                         controlled COA/FX policy input bundles
├── docs/mybee_phase1/                   PROPOSED: source manifest, approvals,
│                                         SRS trace / M1-M2 acceptance evidence
├── tests/mybee_phase1/                  PROPOSED: contract / E2E / privacy tests
└── apps/nex-ae-web/                     EXISTING: optional domain read-only view

Separate repos — reference/source only, NOT required to merge:
- 2608_nsl: immutable admitted runtime + signed wheel
- 2611_MyBee_Blueprint: D04/D12 business-source docs
- 2611_MyBee_Service: NOT a Phase-1 prerequisite
- 2611_nex_eos: NOT a Phase-1 prerequisite
```

**Ownership is by service/database, not by Git folder location.** OA is authoritative for authentication/principal/bindings/current authorization; WC for human WorkItem/Claim/Decision; EOS for Employee/Org business master references, Project/Approval business state, voucher/journal/FX/cost/budget/P&L; AE/NSL/WA for agent execution, admitted controlled write and evidence; MyBee for FL work definitions/templates/payroll/purchase policies. In a deployed company ledger there must be exactly one authoritative EOS journal and migration line.

| Boundary | Allow | Prohibit | CI evidence |
|---|---|---|---|
| MyBee → EOS | Versioned EOS public/authorized Business API + contract stubs | EOS ORM, `NEX_EOS_DATABASE_URL`, `INSERT/UPDATE`, private repository import | AST/import + env scanner; integration negative test |
| EOS → MyBee | Data references accepted through canonical API, verified source evidence | MyBee payroll policy imported into `nex_eos`; parallel GL | EOS-only migration owner and import boundary audit |
| EOS ↔ WC/OA | Human decision evidence + live authorization check | Global ACID or spoofed service claims | cross-service deny/stale-proof tests |
| AE/NSL → EOS | Admitted `WRITE CREATE` Journal creation, `READ` verification | new `OperationKind.POST`, altered P8 draft v1 | NSL conformance + Golden A negative/regression |
| Public E2E → runtime | Browser or public Platform API start, process-driven transitions | direct WorkItem/Journal/Outbox/WA state injection in test runner | Golden Journey transition audit |

### 1.1 Financial transaction invariants

- `BusinessDocument approval` ≠ `Accounting Human Approval` ≠ `NSL WRITE admission/approval` ≠ `EOS Journal Posting`. None substitutes for another.
- P8/Golden A v1 `FINANCE.CREATE_VOUCHER_DRAFT` stays unchanged. Existing `eos_voucher_draft` `DRAFT`-only constraint is never repurposed as a posted ledger.
- New v2 Candidate has exact source revision/hash, company/project scope and validated accounts/period/FX; `POSTED Journal` is immutable, correction via approved reversal.
- **Exactly one EOS DB transaction** commits approval acceptance/consumption, posted journal & lines, candidate state, operation idempotency and outbox. Cross-service calls rely on evidence/reconcile, not distributed ACID.
- `UNKNOWN_COMMIT_STATE` is not ordinary failure; query authoritative EOS and reconcile before retry. Duplicate financial side effects = forbidden.
- Project Actual P&L derives only from eligible POSTED GL, deterministic allocation and conserved amount, with budget/provisional/unknown/unallocated and watermark separated.
- USD and other FX use original trade currency plus KRW functional amounts and immutable approved FX rate-source/date/session/snapshot evidence; financial and tax policies are not silently conflated.
- No real payroll amount in unauthorized P&L API, logs, artifacts or tests. Protected employee PII remains outside OA `user` identity row.

## 2. Milestones: vertical value first, formal full closure later

| Milestone | Meaning | Mandatory evidence | Not sufficient |
|---|---|---|---|
| **M1 — Early Integrated Vertical Slice** | Actual IA/PA → WC human approval → accountant → NSL/EOS posted journal → allocation → P&L → PA/WA evidence | Public API initiated E2E, real test-DB constraints, synthetic USD FX Snapshot, one journal, project A/B amounts, OA negative, Golden A unchanged | Mock-only execution, direct DB transition setup, `candidate` treated as posted, period-close/revaluation skipped and called Phase-1 final |
| **M2 — Formal Phase-1 Closure** | All SRS MUST with FX settlement/revaluation/close, D08/D15, privacy/stock, full E2E/PG, source signoffs | 116 trace, 18 PG faults, 12 E2E, P8/Golden A full regression, accounting policy approval, PDF semantic gate, RC | Document review alone, migration dry-run only, no artifact evidence |

**Precise reordering:** Previously `S8-02` closure depended on `S5-04`, which itself depended on monetary remeasurement `S5-02`. Requiring all of those before the first PA/P&L journey undermines “early M1.” v1.2 introduces **checkpoint-only** `CP-M1-S8-02` and `CP-M1-E2E-FX-01`, dependent on basic EOS posting verification `S4-02/S4-04`, while the *complete original* `S8-02/S8-03` packets retain their v1.0 dependencies and close at M2. This is a sequencing change, not a relaxation of posting safety or NSL semantics.

### 2.1 M1 incremental checkpoints (each independently testable; do not label M1 PASS prematurely)

| Checkpoint ID | Depends on | Acceptance proof |
|---|---|---|
| `CP-M1-PA-WORK` | `S0-02`, `S1-05`, `MB1-02` | IA→PA(Registry)→WC DELEGATE/Claim + Project WorkCodeSet/Scope; real process trace, no fake transitions |
| `CP-M1-BUSINESS-PROOF` | `S2-03`, `S3-03`, `MB2-01` | WC Human Business Approval + EOS accepted final proof + distinct accountant review state; no posting yet |
| `CP-M1-JOURNAL` | `S4-03`, `S4-04` | Approval+Posting single EOS PostgreSQL transaction, idempotent retry and UNKNOWN recovery |
| `CP-M1-PNL` | `S6-03`, `S7-02`, `S7-03` | POSTED GL → SourcePool → deterministic split → authorized P&L with watermark, no double count |
| `CP-M1-S8-02` | `S8-01`, `S4-02`, `S4-04` | S8-02 checkpoint ONLY: AE/NSL journal WRITE CREATE, immediate EOS read-after-write verification, typed UNKNOWN lookup; full S8-02 depends on S5-04 at M2 |
| `CP-M1-MB8-01` | `S8-01`, `CP-M1-S8-02`, `MB1-01` | MB8-01 checkpoint ONLY: signed minimal D04/D12 skill + FL mapping, PA/NSL invocation; full MB8-01 closes in M2 |
| `CP-M1-E2E-FX-01` | `CP-M1-PA-WORK`, `CP-M1-BUSINESS-PROOF`, `CP-M1-JOURNAL`, `CP-M1-PNL`, `CP-M1-S8-02`, `CP-M1-MB8-01`, `MB3-01`, `MB1-03` | S8-03 checkpoint ONLY: true public API/browser IA→PA→WC/OA→EOS USD Journal→Allocation/P&L→WA result, original S8-03 closes at M2 |

`CP-M1-E2E-FX-01` is the *only* full M1 declaration Gate. Prior checkpoint success is useful implementation evidence but is not the M1 completion claim. Any PA path not yet available in master must be implemented/gated, not replaced with direct test calls to EOS or WC private state.

### 2.2 M1 deterministic synthetic example (`E2E-D04D12-FX-01`)

Fixture is illustrative, **not a live bank rate**: KRW functional currency Company C, Projects A/B, expense USD 10,000.00, approved trade-date USD/KRW reference rate 1,350.20, A=40%, B=60%, period OPEN, signed company-scope business document and separate human accounting approval.

| Runtime step | Required assertion |
|---|---|
| 1. Public AE/IA → PA delegated work and Claim | Real AE Registry agent/PA, WC work identity, Project A/B and D12 required five FL codes assigned; tenant/company/project OA scope checked |
| 2. Draft/proposal → WC BusinessFormal → EOS Proof | Exact approved document revision/hash, company/PROJECT_SET scope; creator cannot self-approve if policy disallows; no GL posting before accounting review |
| 3. FX rate policy and candidate | Immutable approved source/published session/transaction date/snapshot hash; `10,000.00 × 1,350.20 = KRW 13,502,000`; candidate Dr/Cr balanced; `PostedJournalCount=0` |
| 4. Human accountant approval | WC Human Decision + EOS accounting Proof; current OA role/SoD/tenant/company/amount scope recheck; still `PostedJournalCount=0` |
| 5. AE/NSL governed single CREATE | Admitted WRITE CREATE to EOS v2 canonical posting API; single PostgreSQL transaction accepts proof and writes immutable journal, candidate state/idempotency/outbox; `PostedJournalCount=1` |
| 6. SourcePool / Allocation | Only eligible POSTED expense. A `KRW 5,400,800`, B `KRW 8,101,200`, total `KRW 13,502,000`, unallocated 0 in this sample; no double count |
| 7. Authorized Project P&L READ | Both Project P&L views reconcile, with event watermark/staleness; deny unauthenticated/non-scoped reads; protected employee fields absent |
| 8. PA/WA WorkResult + retry audit | Runtime records authoritative journal/allocation/FX snapshot references, redacted result; repeated call returns original result; lost ACK reconciled without second journal |

**Journal modeling note:** Example assumes immediately expense-eligible service/operating cost. Goods purchased to inventory (e.g. 120 units with 20 units remaining) must not be treated as 120 units of current Project expense; only recognized consumption qualifies. FX settlement and closing remeasurement remain **M2 mandatory**, not covered by the illustrative M1 rate snapshot. `FINANCE.JOURNAL` is the SoR; Project P&L is a read projection.

## 3. Short branch/PR implementation chronology — ONE repository

Every branch is created from a clean/updated `master`; proposals below are *labels*, not created Git branches/PR numbers. A large wave must be split into several reviewable packet PRs. Only the same NeX `master` receives merges; no cross-repository consumer PR is required in Phase-1. NSL source changes require a separate independent controlled amendment and wheel admission and are intentionally **out of scope**.

```text
NeX master @ pinned SHA + S0 baseline
   |
 W00  S0-01/02/03 + MB0-01/02  [Frozen & Golden A guards]
   |
 W10  MB1-01 FL Catalog -> S1-01..06 + MB1-02/03
   |   (LegalEntity / COA / Period / approved FX / D12 Project readiness)
 W20  S2-01..04 + MB2-01  [Business Proof, COMPANY/PROJECT_SET,
   |                         Accountant Human Approval, SoD]
 W30  S3-01..03 + MB3-01  [VoucherCandidate v2, v1 preserved]
   |
 W40  S4-01..04  [Journal immutable, atomic posting, replay/UNKNOWN]
   |                   W50  S6-01..03       S7-01 budget foundation (parallel after S4)
   |                  /
 W60  S7-02/03 [Project P&L / read access / privacy]
   |
 W70  S8-01 + CP-M1-S8-02 + CP-M1-MB8-01 + CP-M1-E2E-FX-01
   |
 === M1: public IA/PA→EOS approval/posting→allocation→P&L→WA ===
   |
 W80  S5-01..04 (reversal/FX remeasurement/period close/reconcile)
   |
 W81  S6-04 generic source intake + MB6-01/02 domain adapters
 W84  S7-04 NVT/close + MB1-04 grade policy + MB7-01 read-only UX
   |
 W90  S8-02/03 full closures + MB8-01 full certified pack
 W93  S8-04  all payroll/inventory/FX close E2E
 W99  S8-05 + MB8-02  full PostgreSQL/Gate/Finance signoffs
   |
 === M2: Formal Phase-1 Closure ===
   |
 ADR-REVIEW-EOS-EXTRACT-P1 (decision gate; no forced extraction)
```

### 3.1 PR/merge Gate policy

- One packet per short branch is default; small coupled schema+code PRs may group 2–3 packets if same owner/mergeable, but the packet IDs remain individually auditable.
- If an API is not yet complete, new route/feature flag must be closed-by-default and avoid activation on production profiles. Do not merge partially enabled accounting posting.
- Provider schema + consumer compatibility fixtures may land in the same NeX PR, but both Contract-Positive and Contract-Negative suites must pass; no need for MyBee second GitHub repo.
- Accounting, OA scope, WC/AE trust, migration runner, new outbox and multi-service changes escalate to Checkpoint/Full Gate immediately; do not wait for cadence.
- Use existing `scripts/quality/run_slice_gate.sh`, `run_checkpoint_gate.sh`, `run_quality_gate.sh` and `validate_contracts.py`; PostgreSQL tests are protected against actual test DB identity.
- Each PR records base/head SHA, exact old/new schema, branch, migration owner, test command/result, risk, rollback or fix-forward, `M1`/`M2` evidence and reviewer. `CODEOWNERS`/Ruleset current enforcement must be independently confirmed, not assumed.

### 3.2 Ordered PR waves with producer/consumer contracts

| Wave | Predecessor / PR ordering | Relevant packets | Exit gate |
|---|---|---|---|
| `W00` | Start | S0-01/02/03, MB0-01/02 | Frozen SHA+Golden A v1+boundary scanning; source access |
| `W10` | W00; MB1-01 catalog before S1-05 | S1-01..06, MB1-01/02/03 | LegalEntity/COA/OPEN period/FX source + five D12 WorkCodeSet |
| `W20` | S1-01/02 and provider v2 contract | S2-01..04, MB2-01 | Company-scoped document proof + WC/OA accountant SoD |
| `W30` | W20 and FX/period | S3-01..03, MB3-01 | Immutable candidate v2, balanced and no GL preposting |
| `W40` | W30 + S1 period | S4-01..04 | Immutable Journal, atomicity, idempotency, loss-ACK reconciliation |
| `W50` | W40 (+ S1-06 readiness) | S6-01..03 and S7-01 | Eligible cost pool/approved allocation/actual-vs-budget model |
| `W60` | W50 | S7-02/03 | P&L GL conservation, OA scope, privacy/watermark |
| `W70` | W40/W60 and admitted Tool schema | S8-01, CP-M1-S8-02, CP-M1-MB8-01, CP-M1-E2E-FX-01 | Public IA/PA journey M1; no direct runtime-transition SQL |
| `W80` | M1; S4 journal available | S5-01..04 | Reversal/settlement/revaluation/close/concurrency + full Journal verify/reconcile |
| `W81/84` | W80/eligible ledger | S6-04, S7-04, MB1-04/MB6-01/02/MB7-01 | Payroll/purchasing evidence, NVT/Project close, UX/privacy |
| `W90/93` | W80/81/84 | S8-02/03 full; MB8-01 full; S8-04 | Signed Skill full tool set, all E2E and provider/consumer acceptance |
| `W99` | All prior | S8-05, MB8-02 | 116 SRS, 18 PG, 12 E2E + finance PDF/FX signoffs + full gate + release |

> Wave labels do **not** force every packet into a single PR. `S8-02`/`S8-03` early checkpoints are reviewed/merged as a minimal isolated subset; only after S5 settlement/reconciliation closure can the complete original packets be marked DONE. The source key `M1_PARTIAL` is never `DONE` until M2. M1 branch is not a long-lived integration branch.

## 4. 37 preserved Codex packets — repository, targets, PR branch, tests, gates

Every entry below is targeted to `nurigitdev/2607_nex_platform:master`. Each includes exact existing review paths (where available) and explicit **PROPOSED** code targets; test paths are inherited from the prior ISP and may also be proposed. For every path Codex must confirm existence and inspect the current interface before editing. `MB*` integrations are listed separately in §5 and are *inside the same repo*.

| Packet | Exit | Wave | PR branch proposed | Proposed primary targets |
|---|---|---|---|---|
| `S0-01` | M1 | `W00` | `docs/mybee-p1-s0-01` | `docs/mybee_phase1/baselines/source_manifest.json`; `docs/mybee_phase1/baselines/repo_compatibility_owners.md` (+1) |
| `S0-02` | M1 | `W00` | `docs/mybee-p1-s0-02` | `docs/mybee_phase1/baselines/v1_regression_results.md` |
| `S0-03` | M1 | `W00` | `docs/mybee-p1-s0-03` | `docs/mybee_phase1/traceability/requirements.v1.1.json`; `tests/test_mybee_d04d12_architecture_snapshot.py` (+1) |
| `S1-01` | M1 | `W10` | `feat/eos/p1-s1-01` | `services/nex-eos/nex_eos/legal_entities.py`; `services/nex-eos/nex_eos/legal_entity_api.py` |
| `S1-02` | M1 | `W10` | `feat/eos/p1-s1-02` | `services/nex-eos/nex_eos/account_catalog.py`; `services/nex-eos/nex_eos/account_policy_api.py` (+1) |
| `S1-03` | M1 | `W10` | `feat/eos/p1-s1-03` | `services/nex-eos/nex_eos/accounting_periods.py`; `services/nex-eos/nex_eos/accounting_period_api.py` |
| `S1-04` | M1 | `W10` | `feat/eos/p1-s1-04` | `services/nex-eos/nex_eos/fx_rates.py`; `services/nex-eos/nex_eos/fx_policy.py` (+2) |
| `S1-05` | M1 | `W10` | `feat/eos/p1-s1-05` | `services/nex-eos/nex_eos/project_work_codes.py`; `services/nex-eos/nex_eos/project_business_api.py` (+1) |
| `S1-06` | M1 | `W10` | `feat/eos/p1-s1-06` | `services/nex-eos/nex_eos/project_work_assignments.py`; `domains/mybee/mybee_ax/domain/workforce_planning.py` |
| `S2-01` | M1 | `W20` | `feat/eos/p1-s2-01` | `services/nex-eos/nex_eos/approved_documents.py`; `services/nex-eos/nex_eos/approved_document_api.py` (+1) |
| `S2-02` | M1 | `W20` | `feat/eos/p1-s2-02` | `services/nex-eos/nex_eos/scoped_approvals.py`; `services/nex-eos/nex_eos/scoped_approval_api.py` (+1) |
| `S2-03` | M1 | `W20` | `feat/eos/p1-s2-03` | `services/nex-eos/nex_eos/accounting_approval.py`; `services/nex-eos/nex_eos/accounting_approval_api.py` (+1) |
| `S2-04` | M1 | `W20` | `feat/eos/p1-s2-04` | `services/nex-eos/nex_eos/approved_document_consumption.py` |
| `S3-01` | M1 | `W30` | `feat/eos/p1-s3-01` | `services/nex-eos/nex_eos/voucher_candidates.py`; `services/nex-eos/nex_eos/finance_v2_api.py` (+1) |
| `S3-02` | M1 | `W30` | `feat/eos/p1-s3-02` | `services/nex-eos/nex_eos/candidate_validation.py`; `domains/mybee/mybee_ax/domain/accounting_rules.py` |
| `S3-03` | M1 | `W30` | `feat/eos/p1-s3-03` | `services/nex-eos/nex_eos/candidate_review.py` |
| `S4-01` | M1 | `W40` | `feat/eos/p1-s4-01` | `services/nex-eos/nex_eos/accounting_posting_admission.py` |
| `S4-02` | M1 | `W40` | `feat/eos/p1-s4-02` | `services/nex-eos/nex_eos/journals.py`; `services/nex-eos/nex_eos/journal_verification.py` |
| `S4-03` | M1 | `W40` | `feat/eos/p1-s4-03` | `services/nex-eos/nex_eos/journal_posting.py` |
| `S4-04` | M1 | `W40` | `feat/eos/p1-s4-04` | `services/nex-eos/nex_eos/journal_operations.py`; `services/nex-eos/nex_eos/journal_outbox_events.py` |
| `S5-01` | M2 | `W80` | `feat/eos/p1-s5-01` | `services/nex-eos/nex_eos/journal_reversal.py` |
| `S5-02` | M2 | `W80` | `feat/eos/p1-s5-02` | `services/nex-eos/nex_eos/fx_remeasurement.py`; `services/nex-eos/nex_eos/monetary_positions.py` |
| `S5-03` | M2 | `W80` | `feat/eos/p1-s5-03` | `services/nex-eos/nex_eos/period_closing.py`; `services/nex-eos/nex_eos/fx_settlement.py` |
| `S5-04` | M2 | `W80` | `feat/eos/p1-s5-04` | `services/nex-eos/nex_eos/journal_read_api.py`; `services/nex-eos/nex_eos/journal_reconciliation.py` |
| `S6-01` | M1 | `W50` | `feat/eos/p1-s6-01` | `services/nex-eos/nex_eos/cost_source_pools.py`; `services/nex-eos/nex_eos/cost_source_pool_api.py` |
| `S6-02` | M1 | `W50` | `feat/eos/p1-s6-02` | `services/nex-eos/nex_eos/allocation_plans.py`; `services/nex-eos/nex_eos/allocation_plan_api.py` |
| `S6-03` | M1 | `W50` | `feat/eos/p1-s6-03` | `services/nex-eos/nex_eos/cost_allocations.py`; `services/nex-eos/nex_eos/allocation_reconciliation.py` (+1) |
| `S6-04` | M2 | `W81` | `feat/eos/p1-s6-04` | `services/nex-eos/nex_eos/cost_source_intake.py`; `services/nex-eos/nex_eos/cost_source_intake_api.py` (+3) |
| `S7-01` | M1 | `W50` | `feat/eos/p1-s7-01` | `services/nex-eos/nex_eos/budgets.py`; `services/nex-eos/nex_eos/project_budget_bindings.py` (+1) |
| `S7-02` | M1 | `W60` | `feat/eos/p1-s7-02` | `services/nex-eos/nex_eos/project_pnl.py`; `services/nex-eos/nex_eos/pnl_projector.py` (+2) |
| `S7-03` | M1 | `W60` | `feat/eos/p1-s7-03` | `services/nex-eos/nex_eos/pnl_privacy.py`; `services/nex-eos/nex_eos/pnl_access.py` (+1) |
| `S7-04` | M2 | `W84` | `feat/eos/p1-s7-04` | `services/nex-eos/nex_eos/project_close_guards.py`; `services/nex-eos/nex_eos/nvt_pnl_rollup.py` |
| `S8-01` | M1 | `W70` | `feat/eos/p1-s8-01` | `contracts/schemas/service/nex_eos/eos_voucher_candidate_create_v2.schema.json`; `contracts/schemas/service/nex_eos/eos_accounting_posting_v2.schema.json` (+8) |
| `S8-02` | M1 checkpoint → M2 close | `W90` | `feat/pa/p1-s8-02-journal` | `services/nex-ae-api/nex_ae_api/nsl_eos_journal_execution.py`; `services/nex-ae-api/nex_ae_api/nsl_eos_journal_reconciliation.py` (+1) |
| `S8-03` | M1 checkpoint → M2 close | `W91` | `test/pa/p1-s8-03-e2e` | `tests/test_nex_eos_mybee_public_journey_provider.py`; `tests/fixtures/mybee_fx_shared_purchase.json` (+1) |
| `S8-04` | M2 | `W93` | `test/mybee/p1-s8-04-e2e` | `tests/test_nex_eos_mybee_domain_compatibility.py`; `tests/fixtures/mybee_payroll_purchase_fx.json` (+1) |
| `S8-05` | M2 | `W99` | `docs/mybee-p1-s8-05-closure` | `docs/mybee_phase1/closure/nex_provider_release_evidence.json`; `docs/mybee_phase1/closure/evidence_manifest.json` (+2) |

### 4.1 Individual Codex packet definitions (37/37)

#### `S0-01` — Frozen/HEAD·DB 기준선 고정

- **Owner / PR:** NeX monorepo `master` ← `docs/mybee-p1-s0-01` (`P1-S0-01`, proposed); wave `W00`; **M1 prerequisite / full packet completion**.
- **Dependencies:** S0 baseline start.
- **Existing sources to audit before edit:** `docs/frozen/v2.1/10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md`<br>`database/nex-eos/README.md`.
- **Proposed changed/created paths:** `docs/mybee_phase1/baselines/source_manifest.json`<br>`docs/mybee_phase1/baselines/repo_compatibility_owners.md`<br>`domains/mybee/compatibility/platform.lock.json`.
- **API / NSL boundary:** 보안/권한/DB 소유권 검증; N/A (runtime tool 미변경).
- **SRS traceability:** `SRS-ARCH-001`, `SRS-ARCH-002`, `SRS-ARCH-004`.
- **pytest/contract test target:** `tests/test_mybee_d04d12_architecture_snapshot.py`.
- **Acceptance/Gate:** Frozen diff=0, 실제 master HEAD/계약 해시/마이그레이션 끝번호 기록; gates `G-ARCH`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S0-02` — P8 Golden A 및 기존 승인 회귀 기준선

- **Owner / PR:** NeX monorepo `master` ← `docs/mybee-p1-s0-02` (`P1-S0-02`, proposed); wave `W00`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S0-01`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/vouchers.py`<br>`services/nex-eos/nex_eos/voucher_commands.py`<br>`services/nex-eos/nex_eos/approval_transitions.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py`.
- **Proposed changed/created paths:** `docs/mybee_phase1/baselines/v1_regression_results.md`.
- **API / NSL boundary:** 기존 /internal/v1/finance/voucher-drafts READ/CREATE; FINANCE.CREATE_VOUCHER_DRAFT (v1 unchanged).
- **SRS traceability:** `SRS-ARCH-005`, `SRS-PRJ-001`, `SRS-VCH-006`.
- **pytest/contract test target:** `tests/test_nex_eos_p8_s15_voucher_draft.py`<br>`tests/test_nex_ae_eos_p8_s66_golden_a_commit_journey.py`.
- **Acceptance/Gate:** 기존 v1 Draft/DRAFT DB CHECK/ACK·NSL 회귀 실패 0; gates `G-V1`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S0-03` — 요구사항 추적·소스 원문·변경통제 Gate

- **Owner / PR:** NeX monorepo `master` ← `docs/mybee-p1-s0-03` (`P1-S0-03`, proposed); wave `W00`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S0-01`.
- **Existing sources to audit before edit:** `contracts/openapi/nex-eos.openapi.yaml`<br>`docs/frozen/v2.1`.
- **Proposed changed/created paths:** `docs/mybee_phase1/traceability/requirements.v1.1.json`<br>`tests/test_mybee_d04d12_architecture_snapshot.py`<br>`docs/mybee_phase1/traceability/nex_srs_links.json`.
- **API / NSL boundary:** Schema/Operation registry 충돌 예비검사; No new Tool activation.
- **SRS traceability:** `SRS-ARCH-003`, `SRS-COM-001`.
- **pytest/contract test target:** `tests/test_mybee_d04d12_traceability.py`.
- **Acceptance/Gate:** 116개 요구사항 누락·중복 0; PDF 미검증은 Open Gate로 표기; gates `G-ARCH`, `G-SRC-PDF`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S1-01` — LegalEntity와 ProjectCompanyBinding

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s1-01` (`P1-S1-01`, proposed); wave `W10`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S0-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/projects.py`<br>`services/nex-eos/nex_eos/project_operations.py`<br>`database/nex-eos/migrations/2504_eos_project_hierarchy.sql`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/legal_entities.py`<br>`services/nex-eos/nex_eos/legal_entity_api.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2516_eos_legal_entity_project_binding.sql`.
- **API / NSL boundary:** FINANCE.LEGAL_ENTITY.GET; company binding command/query; READ: FINANCE.LEGAL_ENTITY.GET.
- **SRS traceability:** `SRS-MST-001`, `SRS-MST-002`, `SRS-MST-004`, `SRS-SEC-009`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_legal_entity.py`.
- **Acceptance/Gate:** 법인 유효기간·프로젝트 법인 귀속 1:1; 가짜 Project 금지; gates `G-MASTER`, `PG-FK`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S1-02` — K-IFRS 채택 계정표/승인 릴리스·PostingRule

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s1-02` (`P1-S1-02`, proposed); wave `W10`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-01`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/accounts.py`<br>`services/nex-eos/nex_eos/account_api.py`<br>`database/nex-eos/migrations/2505_eos_account.sql`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/account_catalog.py`<br>`services/nex-eos/nex_eos/account_policy_api.py`<br>`domains/mybee/config/account_catalog/approved_seed_manifest.json`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2517_eos_account_catalog_accounting_period.sql`.
- **API / NSL boundary:** FINANCE.ACCOUNT.CATALOG_GET; FINANCE.ACCOUNT.CREATE_APPROVED; READ: FINANCE.ACCOUNT.CATALOG_GET; governed CREATE.
- **SRS traceability:** `SRS-ACC-001`, `SRS-ACC-002`, `SRS-ACC-003`, `SRS-ACC-005`, `SRS-ACC-006`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_account_policy.py`.
- **Acceptance/Gate:** 원본 계정표 seed hash·승인; leaf/유효일/통화/monetary 구분; gates `G-COA`, `PG-ACCOUNT`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S1-03` — AccountingPeriod·Close/Post 동시성 기반

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s1-03` (`P1-S1-03`, proposed); wave `W10`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-01`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/business_transactions.py`<br>`services/nex-eos/nex_eos/persistence.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/accounting_periods.py`<br>`services/nex-eos/nex_eos/accounting_period_api.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2517_eos_account_catalog_accounting_period.sql`.
- **API / NSL boundary:** FINANCE.PERIOD.GET; FINANCE.PERIOD.CLOSE (Close gate S5); READ: FINANCE.PERIOD.GET; later governed WRITE.
- **SRS traceability:** `SRS-PER-001`, `SRS-PER-002`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_period_lock_pg.py`.
- **Acceptance/Gate:** 동일 period FOR UPDATE 잠금과 OPEN/CLOSING/CLOSED 전이; gates `G-PERIOD`, `PG-RACE`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S1-04` — 매매기준율 정책·FX RateSnapshot·Feed

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s1-04` (`P1-S1-04`, proposed); wave `W10`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-01`, `S1-02`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/accounts.py`<br>`services/nex-eos/nex_eos/business_transactions.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_post_write_verification.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/fx_rates.py`<br>`services/nex-eos/nex_eos/fx_policy.py`<br>`services/nex-eos/nex_eos/fx_api.py`<br>`domains/mybee/config/fx/approved_rate_source_policy.json`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2518_eos_fx_rate_policy_snapshot.sql`.
- **API / NSL boundary:** FINANCE.FX_RATE.IMPORT; FINANCE.FX_RATE.RESOLVE; READ: FINANCE.FX_RATE.RESOLVE; approved source WRITE.
- **SRS traceability:** `SRS-FX-001`, `SRS-FX-005`, `SRS-FX-006`, `SRS-FX-007`, `SRS-FX-008`, `SRS-FX-009`, `SRS-FX-018`, `SRS-FX-021`, `SRS-FX-022`, `SRS-FX-024`, `SRS-SEC-008`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_fx_rate.py`.
- **Acceptance/Gate:** 공식 출처/고시회차/일자/quote_unit/version·원문 해시·휴일 실패닫기; gates `G-FX`, `G-COA`, `PG-FX`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S1-05` — D12 필수 5 FL코드 및 BusinessReady Gate

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s1-05` (`P1-S1-05`, proposed); wave `W10`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-01`, `MB1-01`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/projects.py`<br>`services/nex-eos/nex_eos/project_operations.py`<br>`services/nex-eos/nex_eos/project_memberships.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/project_work_codes.py`<br>`services/nex-eos/nex_eos/project_business_api.py`<br>`domains/mybee/mybee_ax/domain/work_codes.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2519_eos_project_work_code_readiness.sql`.
- **API / NSL boundary:** PROJECT.WORK_CODE_SET.GET/APPROVE; readiness query; READ GET; WRITE APPROVE UPDATE (admitted 0.2.1 only).
- **SRS traceability:** `SRS-PRJ-002`, `SRS-PRJ-003`, `SRS-PRJ-004`, `SRS-PRJ-008`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_work_code_ready.py`.
- **Acceptance/Gate:** FL0012004/005/006/013/026 필수; v1 ACTIVE와 BUSINESS_READY 분리; gates `G-PROJECT`, `PG-WORKCODE`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S1-06` — Project WorkAssignment·Grade/MD 계획

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s1-06` (`P1-S1-06`, proposed); wave `W10`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-05`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/project_memberships.py`<br>`services/nex-eos/nex_eos/project_api.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/project_work_assignments.py`<br>`domains/mybee/mybee_ax/domain/workforce_planning.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2519_eos_project_work_code_readiness.sql`.
- **API / NSL boundary:** Project work assignment command/query; New domain Tool contract after OA admission.
- **SRS traceability:** `SRS-PRJ-005`, `SRS-PRJ-006`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_work_assignment.py`.
- **Acceptance/Gate:** Grade/MD와 개인 실제급여 분리; OA Scope 필수; gates `G-PROJECT`, `G-PRIVACY`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S2-01` — 기안/품의 ApprovedDocumentEnvelope

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s2-01` (`P1-S2-01`, proposed); wave `W20`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-01`, `S1-02`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/approval_instances.py`<br>`services/nex-eos/nex_eos/approval_transitions.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/approved_documents.py`<br>`services/nex-eos/nex_eos/approved_document_api.py`<br>`domains/mybee/mybee_ax/domain/documents.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2520_eos_document_approval_envelope.sql`.
- **API / NSL boundary:** BUSINESS.DOCUMENT_APPROVED.GET; READ proof by EOS and hash; no direct approval bypass.
- **SRS traceability:** `SRS-DOC-001`, `SRS-DOC-002`, `SRS-DOC-007`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_document_envelope.py`.
- **Acceptance/Gate:** 최종 BUSINESS_FORMAL proof/문서 revision/첨부/한도/법인 정확 결합; gates `G-DOC`, `PG-PROOF`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S2-02` — 회사/다수 Project ScopedApprovalCase v2

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s2-02` (`P1-S2-02`, proposed); wave `W20`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-01`, `S2-01`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/approval_policies.py`<br>`services/nex-eos/nex_eos/approval_instances.py`<br>`services/nex-eos/nex_eos/business_formal_wc.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/scoped_approvals.py`<br>`services/nex-eos/nex_eos/scoped_approval_api.py`<br>`domains/mybee/mybee_ax/integrations/nex_approval_client.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2521_eos_scoped_approval_case_v2.sql`.
- **API / NSL boundary:** FINANCE.ACCOUNTING_APPROVAL.REQUEST (v2 case); WRITE CREATE request only; Human WC decision separate.
- **SRS traceability:** `SRS-MST-003`, `SRS-SEC-001`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_approval_company.py`.
- **Acceptance/Gate:** v1 project_id NOT NULL 유지; COMPANY/PROJECT_SET 회사 기반; gates `G-HUMAN`, `PG-SCOPE`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S2-03` — 회계 Human SoD·OA/WC 이벤트 어댑터

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s2-03` (`P1-S2-03`, proposed); wave `W20`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S2-02`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/approval_decision_api.py`<br>`services/nex-eos/nex_eos/approval_transitions.py`<br>`services/nex-eos/nex_eos/authorization.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/accounting_approval.py`<br>`services/nex-eos/nex_eos/accounting_approval_api.py`<br>`domains/mybee/mybee_ax/domain/accounting_signoff_view.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2521_eos_scoped_approval_case_v2.sql`.
- **API / NSL boundary:** FINANCE.ACCOUNTING_APPROVAL.REQUEST + WC event; No agent self-approve; OA human finance:journal:approve.
- **SRS traceability:** `SRS-APR-001`, `SRS-APR-002`, `SRS-APR-003`, `SRS-APR-005`, `SRS-APR-008`, `SRS-FX-023`, `SRS-SEC-002`, `SRS-SEC-003`, `SRS-SEC-005`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_approval_human.py`.
- **Acceptance/Gate:** 중복/역순/권한철회/자기승인 거부; 회계 Proof v2; gates `G-HUMAN`, `PG-OA`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S2-04` — 품의 승인금액 소비·중복청구 Guard

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s2-04` (`P1-S2-04`, proposed); wave `W20`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S2-01`, `S2-02`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/business_transactions.py`<br>`services/nex-eos/nex_eos/approval_instances.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/approved_document_consumption.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2520_eos_document_approval_envelope.sql`.
- **API / NSL boundary:** Document allowance GET; Consumption EOS-only in S4 Posting; READ validation; no stand-alone consumption WRITE.
- **SRS traceability:** `SRS-DOC-003`, `SRS-DOC-004`, `SRS-DOC-005`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_doc_consumption_pg.py`.
- **Acceptance/Gate:** 법인·통화별 한도와 source invoice uniqueness; S4와 동일 UoW; gates `G-DOC`, `PG-CONCURRENCY`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S3-01` — VoucherCandidate v2 불변 Revision/Line

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s3-01` (`P1-S3-01`, proposed); wave `W30`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-02`, `S2-01`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/vouchers.py`<br>`services/nex-eos/nex_eos/voucher_commands.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/voucher_candidates.py`<br>`services/nex-eos/nex_eos/finance_v2_api.py`<br>`domains/mybee/mybee_ax/integrations/nex_voucher_candidate_client.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2522_eos_voucher_candidate_v2.sql`.
- **API / NSL boundary:** FINANCE.VOUCHER_CANDIDATE.CREATE_V2; WRITE CREATE_DRAFT; existing v1 unchanged.
- **SRS traceability:** `SRS-VCH-001`, `SRS-VCH-002`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_voucher_candidate.py`.
- **Acceptance/Gate:** 사업승인 없이는 후보 생성 0; 회사 공용 헤더 project_id 필수 금지; gates `G-CANDIDATE`, `G-V1`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S3-02` — Candidate 회계규칙·FX·기간/균형 검증

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s3-02` (`P1-S3-02`, proposed); wave `W30`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S3-01`, `S1-04`, `S1-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/vouchers.py`<br>`services/nex-eos/nex_eos/accounts.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/candidate_validation.py`<br>`domains/mybee/mybee_ax/domain/accounting_rules.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2522_eos_voucher_candidate_v2.sql`.
- **API / NSL boundary:** FINANCE.VOUCHER_CANDIDATE.VALIDATE; READ/validation Tool; no GL side-effect.
- **SRS traceability:** `SRS-ACC-004`, `SRS-ARCH-007`, `SRS-FX-002`, `SRS-FX-003`, `SRS-FX-004`, `SRS-FX-010`, `SRS-FX-011`, `SRS-VCH-005`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_voucher_fx_validation.py`.
- **Acceptance/Gate:** Dr/Cr 기능통화 균형, immutable FX/rule snapshots, 휴일/단위/미확정 차단; gates `G-FX`, `G-CANDIDATE`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S3-03` — Review Submit/Return/Invalidate 상태 머신

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s3-03` (`P1-S3-03`, proposed); wave `W30`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S3-02`, `S2-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/approval_transitions.py`<br>`WC ApprovalWorkItem`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/candidate_review.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2522_eos_voucher_candidate_v2.sql`.
- **API / NSL boundary:** FINANCE.ACCOUNTING_APPROVAL.REQUEST; candidate review GET; WRITE CREATE review case; NO POST on WC result.
- **SRS traceability:** `SRS-VCH-004`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_candidate_review.py`.
- **Acceptance/Gate:** 변경 시 승인 무효, immutable revision + compare-and-swap; gates `G-CANDIDATE`, `G-HUMAN`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S4-01` — Accounting Proof 수용·현재 OA 재검증

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s4-01` (`P1-S4-01`, proposed); wave `W40`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S2-03`, `S3-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/approval_transitions.py`<br>`services/nex-eos/nex_eos/authorization.py`<br>`services/nex-eos/nex_eos/approval_instances.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/accounting_posting_admission.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql`.
- **API / NSL boundary:** FINANCE.VOUCHER.APPROVE_AND_POST (admission); NSL WRITE R5; OA freshness + exact human proof.
- **SRS traceability:** `SRS-APR-004`, `SRS-APR-007`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_accountant_proof.py`.
- **Acceptance/Gate:** DOCUMENT_SIGNOFF ≠ ACCOUNTING_POSTING, stale/자기승인 실패닫기; gates `G-HUMAN`, `G-GL-ACID`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S4-02` — Immutable PostedJournal·JournalLine/DB 보호

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s4-02` (`P1-S4-02`, proposed); wave `W40`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-03`, `S3-02`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/business_transactions.py`<br>`2506_eos_voucher_draft.sql KEEP`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/journals.py`<br>`services/nex-eos/nex_eos/journal_verification.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql`.
- **API / NSL boundary:** FINANCE.JOURNAL.GET/VERIFY; READ verification + signed journal result.
- **SRS traceability:** `SRS-ACC-007`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_journal_immutable_pg.py`.
- **Acceptance/Gate:** JournalHeader/Line 불변 및 UNIQUE posting/period/계정 snapshot; gates `G-GL-ACID`, `PG-IMMUTABLE`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S4-03` — Posting 원자적 단일 EOS Transaction

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s4-03` (`P1-S4-03`, proposed); wave `W40`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S4-01`, `S4-02`, `S2-04`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/business_transactions.py`<br>`services/nex-eos/nex_eos/persistence.py`<br>`services/nex-eos/nex_eos/outbox_publication.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/journal_posting.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql`.
- **API / NSL boundary:** FINANCE.VOUCHER.APPROVE_AND_POST; WRITE CREATE immutable journal; no POST OperationKind.
- **SRS traceability:** `SRS-ARCH-008`, `SRS-ARCH-009`, `SRS-VCH-003`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_posting_atomic_pg.py`.
- **Acceptance/Gate:** ProofAcceptance+Journal+consumption+candidate CAS+Idem+Outbox 전부 1 Commit; gates `G-GL-ACID`, `PG-FAULT`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S4-04` — Posting Replay·Outbox·UNKNOWN 복구

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s4-04` (`P1-S4-04`, proposed); wave `W40`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S4-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/business_transactions.py`<br>`services/nex-eos/nex_eos/outbox_publication.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_reconciliation.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/journal_operations.py`<br>`services/nex-eos/nex_eos/journal_outbox_events.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql`.
- **API / NSL boundary:** FINANCE.JOURNAL.RECONCILE; READ authoritative business operation; NSL typed UNKNOWN.
- **SRS traceability:** `SRS-APR-006`, `SRS-ARCH-006`, `SRS-SEC-007`, `SRS-VCH-007`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_posting_replay_pg.py`.
- **Acceptance/Gate:** 20경합 1장, ACK유실 조회, same key/hash replay, outbox 중복 안전; gates `G-GL-ACID`, `G-RECOVERY`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S5-01` — 역분개·정정 처리

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s5-01` (`P1-S5-01`, proposed); wave `W80`; **M2 completion**.
- **Dependencies:** `S4-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/vouchers.py`<br>`services/nex-eos/nex_eos/business_transactions.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/journal_reversal.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql`.
- **API / NSL boundary:** FINANCE.JOURNAL.REVERSE; WRITE CREATE new approved reversal journal.
- **SRS traceability:** `SRS-DOC-006`, `SRS-FX-016`, `SRS-VCH-008`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_journal_reversal.py`.
- **Acceptance/Gate:** 원 GL 변경 0, fresh approval/새 기간, allocation compensation; gates `G-REVERSAL`, `PG-IMMUTABLE`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S5-02` — 외화 화폐성 항목 기말평가

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s5-02` (`P1-S5-02`, proposed); wave `W80`; **M2 completion**.
- **Dependencies:** `S4-03`, `S1-04`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/account_catalog.py`<br>`services/nex-eos/nex_eos/fx_rates.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/fx_remeasurement.py`<br>`services/nex-eos/nex_eos/monetary_positions.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql`.
- **API / NSL boundary:** FINANCE.FX_REMEASUREMENT.RUN; WRITE CREATE_DRAFT/CREATE candidate; Human POST later.
- **SRS traceability:** `SRS-FX-012`, `SRS-FX-013`, `SRS-FX-015`, `SRS-FX-017`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_fx_remeasurement_pg.py`.
- **Acceptance/Gate:** K-IFRS monetary only, 금액 Snapshot·revaluation journal/세무정책 분리; gates `G-FX`, `PG-FX-CLOSE`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S5-03` — Period Closing Gate·외화 결제·환차손익

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s5-03` (`P1-S5-03`, proposed); wave `W80`; **M2 completion**.
- **Dependencies:** `S5-02`, `S1-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/accounting_periods.py`<br>`services/nex-eos/nex_eos/journals.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/period_closing.py`<br>`services/nex-eos/nex_eos/fx_settlement.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql`.
- **API / NSL boundary:** FINANCE.PERIOD.CLOSE; settlement approved flow; CREATE_DRAFT -> Human -> CREATE journal.
- **SRS traceability:** `SRS-FX-014`, `SRS-PER-003`, `SRS-PER-004`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_period_close_fx_pg.py`.
- **Acceptance/Gate:** OPEN 경합 일관성·closing-rate 및 미처리 UNKNOWN 차단; gates `G-FX`, `G-PERIOD`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S5-04` — Journal Verify/Recon/GL 조회·오류 복구

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s5-04` (`P1-S5-04`, proposed); wave `W80`; **M2 completion**.
- **Dependencies:** `S4-04`, `S5-02`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/business_queries.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_post_write_verification.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/journal_read_api.py`<br>`services/nex-eos/nex_eos/journal_reconciliation.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql`.
- **API / NSL boundary:** FINANCE.JOURNAL.GET/VERIFY/RECONCILE; READ post-write verification + exact hashes.
- **SRS traceability:** `SRS-FX-020`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_journal_verification.py`.
- **Acceptance/Gate:** COMMITTED + VERIFY_FAILED 별도 경고, 재기표 금지; gates `G-RECOVERY`, `PG-QUERY`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S6-01` — POSTED GL SourcePool 적격성

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s6-01` (`P1-S6-01`, proposed); wave `W50`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S4-03`, `S1-01`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/journals.py`<br>`services/nex-eos/nex_eos/account_catalog.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/cost_source_pools.py`<br>`services/nex-eos/nex_eos/cost_source_pool_api.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql`.
- **API / NSL boundary:** Cost source pool internal read admission; READ eligible component; no manual GL duplication.
- **SRS traceability:** `SRS-ALC-001`, `SRS-ALC-002`, `SRS-ALC-003`, `SRS-ALC-010`, `SRS-ALC-011`, `SRS-ALC-012`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_cost_pool.py`.
- **Acceptance/Gate:** 비용계정만, 자산/AP/예수금·FX 구분, source unique + company; gates `G-ALLOCATION`, `PG-POOL`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S6-02` — Allocation Plan 릴리스·배부 정책

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s6-02` (`P1-S6-02`, proposed); wave `W50`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S6-01`, `S1-06`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/project_work_assignments.py`<br>`services/nex-eos/nex_eos/project_memberships.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/allocation_plans.py`<br>`services/nex-eos/nex_eos/allocation_plan_api.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql`.
- **API / NSL boundary:** Allocation plan approve/read v2; WRITE CREATE/UPDATE only admitted; Human plan approval.
- **SRS traceability:** .
- **pytest/contract test target:** `tests/test_nex_eos_mybee_allocation_plan.py`.
- **Acceptance/Gate:** 업무실적→계획→인력매개→지정비율 원천/승인 hash; gates `G-ALLOCATION`, `PG-POLICY`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S6-03` — Deterministic Allocation Batch·대사

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s6-03` (`P1-S6-03`, proposed); wave `W50`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S6-02`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/business_transactions.py`<br>`services/nex-eos/nex_eos/outbox_publication.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/cost_allocations.py`<br>`services/nex-eos/nex_eos/allocation_reconciliation.py`<br>`services/nex-eos/nex_eos/cost_allocation_api.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql`.
- **API / NSL boundary:** FINANCE.COST_ALLOCATION.RUN/VERIFY; WRITE CREATE batch + READ VERIFY.
- **SRS traceability:** `SRS-ALC-006`, `SRS-ALC-007`, `SRS-ALC-008`, `SRS-ALC-009`, `SRS-ALC-013`, `SRS-ALC-014`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_allocation_pg.py`.
- **Acceptance/Gate:** E=D+A+U 정확; 20경합 1 Batch; DIRECT/MANAGEMENT 배타; gates `G-ALLOCATION`, `PG-CONSERVE`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S6-04` — D08 Payroll / D15 Purchase 최소 소스 어댑터

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s6-04` (`P1-S6-04`, proposed); wave `W81`; **M2 completion**.
- **Dependencies:** `S6-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/allocation_plans.py`<br>`services/nex-eos/nex_eos/journals.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/cost_source_intake.py`<br>`services/nex-eos/nex_eos/cost_source_intake_api.py`<br>`domains/mybee/mybee_ax/integrations/payroll_source.py`<br>`domains/mybee/mybee_ax/integrations/purchasing_source.py`<br>`tests/mybee_phase1/test_domain_cost_adapters.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql`.
- **API / NSL boundary:** D08/D15 source ingest → approved candidate v2; NSL domain Skill invokes canonical EOS tools.
- **SRS traceability:** `SRS-ALC-004`, `SRS-ALC-015`.
- **pytest/contract test target:** `tests/test_mybee_domain_cost_pilots.py`.
- **Acceptance/Gate:** 급여 개인금액 차단, 구매 120/100/20 재고, FX gain 기본 공용 미귀속; gates `G-ALLOCATION`, `G-PRIVACY`; existing Golden A regression when financial/approval contracts touch shared code.
- **Split within one repository:** provider generic Source Intake API stays under `nex_eos`; D08/D15 adapters live under `domains/mybee`; no payroll/Purchase business policy inside EOS or `_shared`.

#### `S7-01` — D04 Budget SoR / D12 Project Budget Link

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s7-01` (`P1-S7-01`, proposed); wave `W50`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S1-05`, `S4-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/projects.py`<br>`services/nex-eos/nex_eos/business_transactions.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/budgets.py`<br>`services/nex-eos/nex_eos/project_budget_bindings.py`<br>`services/nex-eos/nex_eos/budget_api.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2526_eos_project_budget_master.sql`.
- **API / NSL boundary:** Budget read/commit v2, D12 readonly link; Governed Budget WRITE, Project READ.
- **SRS traceability:** .
- **pytest/contract test target:** `tests/test_nex_eos_mybee_budget.py`.
- **Acceptance/Gate:** 예산 하나의 SoR, 승인 예산 고정/실적은 GL·Allocation 파생; gates `G-BUDGET`, `PG-BUDGET`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S7-02` — Project P&L Query/Projection·Watermark

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s7-02` (`P1-S7-02`, proposed); wave `W60`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S6-03`, `S7-01`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/journals.py`<br>`services/nex-eos/nex_eos/outbox_publication.py`<br>`services/nex-eos/nex_eos/projects.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/project_pnl.py`<br>`services/nex-eos/nex_eos/pnl_projector.py`<br>`services/nex-eos/nex_eos/pnl_api.py`<br>`domains/mybee/mybee_ax/integrations/nex_pnl_client.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2527_eos_project_pnl_projection.sql`.
- **API / NSL boundary:** FINANCE.PROJECT_PNL.GET; READ scoped P&L, no new monetary SoR.
- **SRS traceability:** `SRS-FX-019`, `SRS-PNL-001`, `SRS-PNL-002`, `SRS-PNL-006`, `SRS-PNL-007`, `SRS-PNL-008`, `SRS-PNL-009`, `SRS-PNL-010`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_project_pnl.py`.
- **Acceptance/Gate:** POSTED actual만; 손익 미기표·지연·미배부 구분, as_of/watermarks; gates `G-PNL`, `PG-PROJECTION`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S7-03` — Executive P&L 보안/소인원 역산 방지

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s7-03` (`P1-S7-03`, proposed); wave `W60`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S7-02`, `S1-06`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/authorization.py`<br>`services/nex-eos/nex_eos/voucher_access.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/pnl_privacy.py`<br>`services/nex-eos/nex_eos/pnl_access.py`<br>`domains/mybee/mybee_ax/domain/pnl_access_projections.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2527_eos_project_pnl_projection.sql`.
- **API / NSL boundary:** FINANCE.PROJECT_PNL.GET; FINANCE.NVT_PNL.GET; READ classification EAC/OA scope.
- **SRS traceability:** `SRS-ALC-005`, `SRS-ARCH-010`, `SRS-PNL-004`, `SRS-PNL-005`, `SRS-SEC-004`, `SRS-SEC-006`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_pnl_privacy.py`.
- **Acceptance/Gate:** PA 개인급여 금지, group/company aggregation·필터 차분 공격 차단; gates `G-PRIVACY`, `PG-RLS`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S7-04` — NVT 롤업·Project 종결/미정산 검증

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s7-04` (`P1-S7-04`, proposed); wave `W84`; **M2 completion**.
- **Dependencies:** `S7-02`, `S5-03`.
- **Existing sources to audit before edit:** `services/nex-eos/nex_eos/projects.py`<br>`services/nex-eos/nex_eos/project_operations.py`.
- **Proposed changed/created paths:** `services/nex-eos/nex_eos/project_close_guards.py`<br>`services/nex-eos/nex_eos/nvt_pnl_rollup.py`.
- **Migration (proposed; never claim applied):** `database/nex-eos/migrations/2527_eos_project_pnl_projection.sql`.
- **API / NSL boundary:** FINANCE.NVT_PNL.GET; project close check; READ authoritative receipts + governed close.
- **SRS traceability:** `SRS-PNL-003`, `SRS-PRJ-007`.
- **pytest/contract test target:** `tests/test_nex_eos_mybee_project_close.py`.
- **Acceptance/Gate:** 후손 1회 합산; 미기표·미배부·미결재·미FX정산 종결 차단; gates `G-PNL`, `G-PROJECT`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S8-01` — NSL Tool JSON Schema·Registry·Skill Pack

- **Owner / PR:** NeX monorepo `master` ← `feat/eos/p1-s8-01` (`P1-S8-01`, proposed); wave `W70`; **M1 prerequisite / full packet completion**.
- **Dependencies:** `S0-03`, `S4-03`, `S6-03`.
- **Existing sources to audit before edit:** `examples/voucher_draft_validation/tools_write.json [NSL repo]`<br>`contracts/schemas/service/nex_eos/create_voucher_draft_command.v1.schema.json [NeX repo]`.
- **Proposed changed/created paths:** `contracts/schemas/service/nex_eos/eos_voucher_candidate_create_v2.schema.json`<br>`contracts/schemas/service/nex_eos/eos_accounting_posting_v2.schema.json`<br>`contracts/schemas/service/nex_eos/eos_cost_allocation_v2.schema.json`<br>`contracts/schemas/service/nex_eos/eos_fx_rate_snapshot_v2.schema.json`<br>`contracts/schemas/service/nex_eos/eos_project_pnl_query_v2.schema.json`<br>`contracts/openapi/nex-eos.openapi.yaml`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py`<br>`domains/mybee/skills/d04_accounting/manifest.json`<br>`domains/mybee/skills/d12_project/manifest.json`<br>`domains/mybee/mybee_ax/integrations/nex_tool_bindings.py`.
- **API / NSL boundary:** All FINANCE/PROJECT v2 operations, existing v1 untouched; NSL 0.2/0.2.1 admitted kinds only, CREATE not POST.
- **SRS traceability:** .
- **pytest/contract test target:** `tests/test_mybee_nsl_contracts.py`.
- **Acceptance/Gate:** 코어 컴파일러 수정 0, canonical contract compile/negative PASS; gates `G-ARCH`, `G-NSL`; existing Golden A regression when financial/approval contracts touch shared code.
- **Split within one repository:** canonical schema/OpenAPI/Tool registry changes live in `contracts/`/AE; FL mapping and signed domain Skill Pack live in `domains/mybee/skills/`. No NSL compiler/runtime change.

#### `S8-02` — AE Binding·NSL Postwrite Verify/Recon

- **Owner / PR:** NeX monorepo `master` ← `feat/pa/p1-s8-02-journal` (`P1-S8-02`, proposed); wave `W90`; **M1 checkpoint only; full original packet completion at M2**.
- **Dependencies:** `S8-01`, `S5-04`.
- **Existing sources to audit before edit:** `services/nex-ae-api/nex_ae_api/nsl_eos_write_execution.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_reconciliation.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_post_write_verification.py`.
- **Proposed changed/created paths:** `services/nex-ae-api/nex_ae_api/nsl_eos_journal_execution.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_journal_reconciliation.py`<br>`services/nex-ae-api/nex_ae_api/nsl_eos_journal_verification.py`.
- **API / NSL boundary:** AE-to-EOS v2 tool binding; WRITE CREATE, typed UNKNOWN, READ_AFTER_WRITE_STRONG.
- **SRS traceability:** `SRS-COM-002`.
- **pytest/contract test target:** `tests/test_nex_ae_mybee_nsl_eos_integration.py`.
- **Acceptance/Gate:** 고정 wheel/hash, 검증 실패 뒤 이중 Posting 0; gates `G-NSL`, `G-RECOVERY`; existing Golden A regression when financial/approval contracts touch shared code.
- **v1.2 early split:** `CP-M1-S8-02` uses S4 journal basic read-after-write and typed UNKNOWN; `S5-04` full period/FX reconciliation is still mandatory for S8-02 full close.

#### `S8-03` — Golden E2E: 승인 USD 공용전표→손익

- **Owner / PR:** NeX monorepo `master` ← `test/pa/p1-s8-03-e2e` (`P1-S8-03`, proposed); wave `W91`; **M1 checkpoint only; full original packet completion at M2**.
- **Dependencies:** `S8-02`, `S7-03`.
- **Existing sources to audit before edit:** `tests/test_nex_ae_eos_p8_s66_golden_a_commit_journey.py`<br>`tests/test_nex_eos_p8_s73_approval_transition.py`.
- **Proposed changed/created paths:** `tests/test_nex_eos_mybee_public_journey_provider.py`<br>`tests/fixtures/mybee_fx_shared_purchase.json`<br>`tests/mybee_phase1/e2e/test_approved_usd_shared_purchase.py`.
- **API / NSL boundary:** E2E-D04D12-FX-01; NSL Candidate/Journal/Allocation/P&L chain.
- **SRS traceability:** .
- **pytest/contract test target:** `tests/test_mybee_d04d12_fx_e2e.py`.
- **Acceptance/Gate:** USD10k×1350.20=KRW13,502,000; 40/60 split, no duplicate; gates `G-E2E`, `G-FX`; existing Golden A regression when financial/approval contracts touch shared code.
- **v1.2 early split:** `CP-M1-E2E-FX-01` validates the public vertical before full S8-02; this does NOT mark all original S8-03 acceptance or 12 E2E cases PASS.

#### `S8-04` — Payroll·Inventory·FX settlement/close E2E

- **Owner / PR:** NeX monorepo `master` ← `test/mybee/p1-s8-04-e2e` (`P1-S8-04`, proposed); wave `W93`; **M2 completion**.
- **Dependencies:** `S8-03`, `S5-03`, `S6-04`.
- **Existing sources to audit before edit:** `docs/mybee_d04d12/traceability/requirements.json`.
- **Proposed changed/created paths:** `tests/test_nex_eos_mybee_domain_compatibility.py`<br>`tests/fixtures/mybee_payroll_purchase_fx.json`<br>`tests/mybee_phase1/e2e/test_payroll_purchase_fx_close.py`.
- **API / NSL boundary:** E2E-D04D12-01..09 and FX-02..03; All admitted NSL provider-independent Tool profiles.
- **SRS traceability:** .
- **pytest/contract test target:** `tests/test_mybee_d04d12_domain_e2e.py`.
- **Acceptance/Gate:** 급여 개인정보/재고/환차손익/외환결산/문서한도 동시 검증; gates `G-E2E`, `G-PRIVACY`; existing Golden A regression when financial/approval contracts touch shared code.

#### `S8-05` — Full Regression·Signoffs·Controlled Release Closure

- **Owner / PR:** NeX monorepo `master` ← `docs/mybee-p1-s8-05-closure` (`P1-S8-05`, proposed); wave `W99`; **M2 completion**.
- **Dependencies:** `S8-04`.
- **Existing sources to audit before edit:** `scripts/quality/run_quality_gate.sh`<br>`scripts/db/run_migrations.py`.
- **Proposed changed/created paths:** `docs/mybee_phase1/closure/nex_provider_release_evidence.json`<br>`docs/mybee_phase1/closure/evidence_manifest.json`<br>`docs/mybee_phase1/releases/phase1/compatibility.lock.json`<br>`docs/mybee_phase1/releases/phase1/mybee_release_evidence.json`.
- **API / NSL boundary:** Full API/PG/E2E & deployment enable switch; NSL wheel admissibility + rollback gates.
- **SRS traceability:** .
- **pytest/contract test target:** `tests/test_mybee_d04d12_release_closure.py`.
- **Acceptance/Gate:** 116 SRS + 18 ACID + 12 E2E 100%, EOS ≥96/94, 12 gate evidence; gates `G-RELEASE`, `G-SRC-PDF`; existing Golden A regression when financial/approval contracts touch shared code.

## 5. 13 retained MB domain adjuncts — rehosted, no second Repository

Previously MB0-01 was named “MyBee new repo Bootstrap.” Its **Phase-1 semantic is now Monorepo Domain Bootstrap** under `domains/mybee/`: installable domain package, import-boundary lint and focused test collection. Do not create `2611_MyBee_Service` or edit independent NSL source to satisfy any MB packet. These 13 adjunct IDs are *not* replacements for the original 37; they supply MyBee policy/consumer artifacts while EOS retains GL SoR.

| MB packet | Checkpoint | Branch proposed | Proposed source/test targets | Required prior packet |
|---|---|---|---|---|
| `MB0-01` Monorepo Domain Bootstrap; no new repository / GitHub rules assumed | M1 | `feat/mybee/p1-mb0-01` | `domains/mybee/pyproject.toml`<br>`domains/mybee/mybee_ax/__init__.py`<br>`.github/workflows/ci.yml`<br>`tests/mybee_phase1/test_bootstrap.py`<br>`domains/mybee/README.md`<br>`tests/mybee_phase1/test_boundary_imports.py` | `S0-01` |
| `MB0-02` In-repo contract/NSL wheel lock and provider–consumer gate (NOT cross-repo release) | M1 | `feat/mybee/p1-mb0-02` | `domains/mybee/compatibility/platform.lock.json`<br>`domains/mybee/compatibility/check_lock.py`<br>`tests/mybee_phase1/contracts/test_nex_api_compatibility.py` | `S0-01`, `S0-03` |
| `MB1-01` Publish immutable MyBee FL work-code catalog before EOS S1-05 import/admission | M1 | `feat/mybee/p1-mb1-01` | `domains/mybee/catalog/work_codes/catalog.v1.json`<br>`domains/mybee/catalog/work_codes/schema.json`<br>`domains/mybee/mybee_ax/domain/work_codes.py`<br>`tests/mybee_phase1/test_work_code_registry.py` | `MB0-01`, `S0-03` |
| `MB1-02` D12 Project templates and five required FL work codes | M1 | `feat/mybee/p1-mb1-02` | `domains/mybee/templates/d12/required_five.json`<br>`domains/mybee/mybee_ax/domain/project_templates.py`<br>`tests/mybee_phase1/test_d12_mandatory_codes.py` | `S1-05` |
| `MB1-03` Approved K-IFRS COA and FX policy input bundle consumed via EOS API, not DB | M1 | `feat/mybee/p1-mb1-03` | `domains/mybee/config/account_catalog/approved_seed_manifest.json`<br>`domains/mybee/config/fx/approved_rate_source_policy.json`<br>`tests/mybee_phase1/test_finance_seed_lineage.py` | `S1-02`, `S1-04` |
| `MB1-04` Grade/MD domain work planning and protected cost inputs | M2 | `feat/mybee/p1-mb1-04` | `domains/mybee/mybee_ax/domain/workforce_planning.py`<br>`tests/mybee_phase1/test_grade_man_day_privacy.py` | `S1-06` |
| `MB2-01` Business proposal form/template + WC/EOS approval consumer | M1 | `feat/mybee/p1-mb2-01` | `domains/mybee/mybee_ax/domain/documents.py`<br>`domains/mybee/mybee_ax/integrations/nex_business_approval_client.py`<br>`tests/mybee_phase1/test_document_signoff.py` | `S2-01`, `S2-02` |
| `MB3-01` Voucher v2 candidate domain adapter and Proof-aware API consumer tests | M1 | `feat/mybee/p1-mb3-01` | `domains/mybee/mybee_ax/integrations/nex_voucher_candidate_client.py`<br>`tests/mybee_phase1/test_voucher_candidate_consumer.py` | `S3-01`, `S3-02` |
| `MB6-01` D08 payroll cost evidence adapter; never expose individual pay | M2 | `feat/mybee/p1-mb6-01` | `domains/mybee/mybee_ax/integrations/payroll_source.py`<br>`tests/mybee_phase1/test_payroll_aggregate_adapter.py` | `S6-01`, `S6-03`, `S6-04` |
| `MB6-02` D15 purchasing shared-cost/stock evidence adapter | M2 | `feat/mybee/p1-mb6-02` | `domains/mybee/mybee_ax/integrations/purchasing_source.py`<br>`tests/mybee_phase1/test_shared_purchase_adapter.py` | `S6-01`, `S6-03`, `S6-04` |
| `MB7-01` P&L executive read-only presentation in existing AE Web (no new app required) | M2 | `feat/mybee/p1-mb7-01` | `apps/nex-ae-web/src/features/mybee/`<br>`domains/mybee/mybee_ax/integrations/nex_pnl_client.py`<br>`tests/mybee_phase1/test_pnl_privacy_consumer.py` | `S7-02`, `S7-03` |
| `MB8-01` MyBee Signed Skill Pack and PA orchestration in monorepo | M1 subset / M2 complete | `feat/mybee/p1-mb8-01` | `domains/mybee/skills/d04_accounting/manifest.json`<br>`domains/mybee/skills/d12_project/manifest.json`<br>`domains/mybee/mybee_ax/integrations/nex_tool_bindings.py`<br>`tests/mybee_phase1/test_mybee_skill_admission.py` | `S8-01`, `S8-02` |
| `MB8-02` In-repo business E2E / compatibility lock / release evidence (not multi-repo deployment) | M2 | `feat/mybee/p1-mb8-02` | `tests/mybee_phase1/e2e/test_approved_usd_shared_purchase.py`<br>`tests/mybee_phase1/e2e/test_payroll_purchase_fx_close.py`<br>`docs/mybee_phase1/releases/phase1/compatibility.lock.json`<br>`docs/mybee_phase1/releases/phase1/consumer_acceptance.json` | `S8-03`, `S8-04`, `S8-05` |

**Boundary corrections for rehosted MB packets:**

- `MB1-01` publishes/version-controls source FL catalog first, then `S1-05` accepts and binds its mandatory five D12 codes; this deliberately reverses the cross-repo consumer-first assumption in v1.1 without changing S1-05 business requirements.
- `MB0-01` adds a domain package/test root and **extends existing** NeX CI where necessary; do not create a new root workflow/CODEOWNERS without an actual approved need.
- `MB7-01` reuses `apps/nex-ae-web/src/features/mybee/` for an optional M2 read-only P&L view, not a duplicate AE app or second frontend auth stack; M1 can use public API evidence only.
- `MB8-01` has an M1 signed minimal D04/D12 Skill subset, then full admitted catalog/coverage closes at M2; the full original MB8-01 depends on the complete S8-02.
- `MB6-01/02` pass payroll/purchasing Source Evidence through EOS canonical APIs, maintaining employee privacy and inventory-consumption eligibility. No standalone MyBee GL or direct PostgreSQL client is allowed.

## 6. EOS Migration registry and one-PR DDL ownership

Candidate migrations `2516..2527` are not in the verified current tree and must be numbered again if other EOS changes land on master. A migration file is created or modified by exactly one designated DDL-owning packet/PR; subsequent dependent packets consume its committed, test-applied schema and may request a new additive migration rather than editing history.

| DDL | Proposed path | Sole DDL author packet | Primary test / gate |
|---|---|---|---|
| `2516` | `database/nex-eos/migrations/2516_eos_legal_entity_project_binding.sql` | `S1-01` | `tests/test_nex_eos_mybee_legal_entity.py`; `G-MASTER, PG-FK` |
| `2517` | `database/nex-eos/migrations/2517_eos_account_catalog_accounting_period.sql` | `S1-02` | `tests/test_nex_eos_mybee_account_policy.py`; `G-COA, PG-ACCOUNT` |
| `2518` | `database/nex-eos/migrations/2518_eos_fx_rate_policy_snapshot.sql` | `S1-04` | `tests/test_nex_eos_mybee_fx_rate.py`; `G-FX, G-COA` |
| `2519` | `database/nex-eos/migrations/2519_eos_project_work_code_readiness.sql` | `S1-05` | `tests/test_nex_eos_mybee_work_code_ready.py`; `G-PROJECT, PG-WORKCODE` |
| `2520` | `database/nex-eos/migrations/2520_eos_document_approval_envelope.sql` | `S2-01` | `tests/test_nex_eos_mybee_document_envelope.py`; `G-DOC, PG-PROOF` |
| `2521` | `database/nex-eos/migrations/2521_eos_scoped_approval_case_v2.sql` | `S2-02` | `tests/test_nex_eos_mybee_approval_company.py`; `G-HUMAN, PG-SCOPE` |
| `2522` | `database/nex-eos/migrations/2522_eos_voucher_candidate_v2.sql` | `S3-01` | `tests/test_nex_eos_mybee_voucher_candidate.py`; `G-CANDIDATE, G-V1` |
| `2523` | `database/nex-eos/migrations/2523_eos_posted_journal_posting.sql` | `S4-02` | `tests/test_nex_eos_mybee_journal_immutable_pg.py`; `G-GL-ACID, PG-IMMUTABLE` |
| `2524` | `database/nex-eos/migrations/2524_eos_fx_monetary_remeasurement.sql` | `S5-01` | `tests/test_nex_eos_mybee_journal_reversal.py`; `G-REVERSAL, PG-IMMUTABLE` |
| `2525` | `database/nex-eos/migrations/2525_eos_cost_source_allocation.sql` | `S6-01` | `tests/test_nex_eos_mybee_cost_pool.py`; `G-ALLOCATION, PG-POOL` |
| `2526` | `database/nex-eos/migrations/2526_eos_project_budget_master.sql` | `S7-01` | `tests/test_nex_eos_mybee_budget.py`; `G-BUDGET, PG-BUDGET` |
| `2527` | `database/nex-eos/migrations/2527_eos_project_pnl_projection.sql` | `S7-02` | `tests/test_nex_eos_mybee_project_pnl.py`; `G-PNL, PG-PROJECTION` |

**Migration rules:** `python scripts/db/run_migrations.py --service nex-eos --profile test --dry-run` verifies only a plan, not actual DDL/constraint durability. Follow it with opt-in guarded TestDB migrations, readback, negative FK/unique/row-lock tests, idempotent runner and rollback strategy. Migration tests may not target dev/prod by accident; keep `NEX_EOS_TEST_DATABASE_URL` and database identity explicit. Signed, posted financial history is never deleted as a rollback shortcut.

## 7. CI and PostgreSQL Acceptance Gate contract

| Gate | Cadence / owner | Required proof (not asserted executed) |
|---|---|---|
| `G-SLICE` | Every source packet, owning service | Focused pytest + service regression + changed-file coverage + contract checks + relevant smoke. |
| `G-CP` | Risk escalation or fifth requirement slice | Checkpoint regression; escalate immediately for auth/schema/multiple service/financial critical changes. |
| `G-FULL` | Tenth/closure/release or high risk | Complete platform pytest/coverage + original Golden A + web regression; no unexplained coverage regression. |
| `G-ARCH` | S0 and every topology/contract change | Frozen SoR unchanged, 37/116 mapping intact, DB/service owner uniqueness, version hashes. |
| `G-V1` | S0 and every EOS/AE write change | Original P8 VoucherDraft v1 + actual signed wheel + Golden A admission/replay/verification unchanged. |
| `G-CONSUMER` | MyBee domain/provider contracts | Positive/negative JSON schema, API consumer auth, no private ORM, exact version lock. |
| `G-NSL` | Tool/PA changes | Only admitted CREATE/CREATE_DRAFT/UPDATE; Journal posting via CREATE, positive/negative trust, typed UNKNOWN/reconciliation. |
| `G-PA` | M1 journey | Real IA/PA/WC/WA runtime work and claim, public entrypoint; no runner-forced internal transitions. |
| `G-PG` | M1 atomic + M2 full | PostgreSQL test DB identity verified; zero partial commit; 18 fault/concurrency cases by M2. |
| `G-E2E` | M1 and M2 | M1 FX-01 one public path; M2 all 12 cases; actual result/proof/ledger assertions and evidence links. |
| `G-FX` | M1 rate and M2 settlement/close | Source/date/session hash immutable; KRW/FX Decimal, real/synthetic labeled; tax/accounting policy separate. |
| `G-PRIVACY` | M1 P&L access and M2 payroll | OA project/company scope, aggregation/suppression, no salary reverse identification. |
| `G-SRC-PDF` | Before M2 release | D04 v1.9/D12 v2.8 PDF & DOCX page/section semantic signoff; deviations tracked. |
| `G-RELEASE` | M2 | Finance/coA/FX/Tax signing, DB migration records, 37+13 packet evidence, 116/18/12 trace, rollback/fix-forward. |

### 7.1 Existing executable script examples (commands are instructions, NOT executed evidence)

```bash
# Before every Codex packet
 git status --short --branch
 git rev-parse HEAD
 git log -1 --oneline
 git ls-files 'database/nex-eos/migrations/*.sql'

# S0 baseline and scoped packet source coverage example (adjust --test/target to actual packet)
 scripts/quality/run_slice_gate.sh --service nex-eos \
   --test tests/test_nex_eos_p8_s15_voucher_draft.py \
   --coverage-target services/nex-eos/nex_eos/vouchers.py

# Escalation for multi-service approval/EOS/NSL or migration/high-risk scope
 scripts/quality/run_checkpoint_gate.sh \
   --test tests/test_nex_ae_eos_p8_s66_golden_a_commit_journey.py
 scripts/quality/run_quality_gate.sh
 ./.venv/bin/python scripts/quality/validate_contracts.py

# Dry-run is not a PostgreSQL PASS; obtain approved guarded test DB separately
 ./.venv/bin/python scripts/db/run_migrations.py --service nex-eos --profile test --dry-run

# Domain packet after tests/mybee_phase1 has been created
 ./.venv/bin/python -m pytest -q tests/mybee_phase1/

# PR evidence (proposed artifact outputs, not already existing)
 # docs/mybee_phase1/evidence/<packet_id>.json
 # reports/quality/... are generated and kept out of git by existing repo policy
```

**Coverage:** Existing repository `docs/development_process.md` describes Slice/Checkpoint ≥95% Statement and ≥94% Branch, Full compatibility ≥95% Statement and ≥85% Branch; this Phase-1 implementation sets EOS-focused new/changed code *target* ≥96% Statement / ≥94% Branch unless leadership approves an explicit exception. Do not present global Full threshold as 96/94 or claim tests were run. For proposed `domains/mybee/` code, add equivalent scoped coverage instrumentation; do not invent a `nex-mybee` service identifier for the existing quality script.

### 7.2 PostgreSQL fault/concurrency acceptance — 18 immutable IDs

| ID | Primary packet | Proposed pytest | Must prove |
|---|---|---|---|
| `T-ACID-01` | `S4-03` | `tests/test_nex_eos_mybee_posting_atomic_pg.py` | After approval acceptance INSERT: all rolled back |
| `T-ACID-02` | `S4-03` | `tests/test_nex_eos_mybee_posting_atomic_pg.py` | Crash after JournalHeader and line #2: header+lines absent |
| `T-ACID-03` | `S4-03` | `tests/test_nex_eos_mybee_posting_atomic_pg.py` | Allowance Consumption insert crash: no POSTED/consumption |
| `T-ACID-04` | `S4-03` | `tests/test_nex_eos_mybee_posting_atomic_pg.py` | CAS before Outbox failure: complete rollback |
| `T-ACID-05` | `S4-04` | `tests/test_nex_eos_mybee_posting_replay_pg.py` | ACK lost after commit: same journal fetched with same ID |
| `T-ACID-06` | `S4-04` | `tests/test_nex_eos_mybee_posting_replay_pg.py` | 20 parallel calls same key: one posted journal |
| `T-ACID-07` | `S4-04` | `tests/test_nex_eos_mybee_posting_replay_pg.py` | same key/different hash -> conflict without alteration |
| `T-ACID-08` | `S1-03` | `tests/test_nex_eos_mybee_period_lock_pg.py` | 20 post vs close writers: period lock serial order |
| `T-ACID-09` | `S2-04` | `tests/test_nex_eos_mybee_doc_consumption_pg.py` | two invoices consuming final allowance: no overspend |
| `T-ACID-10` | `S2-03` | `tests/test_nex_eos_mybee_approval_human.py` | duplicate/late WC decision: no false approval |
| `T-ACID-11` | `S4-01` | `tests/test_nex_eos_mybee_accountant_proof.py` | OA revoke pre-admission: zero journal |
| `T-ACID-12` | `S4-04` | `tests/test_nex_eos_mybee_posting_replay_pg.py` | Outbox down after GL COMMIT: GL retained/stale projector |
| `T-ACID-13` | `S6-03` | `tests/test_nex_eos_mybee_allocation_pg.py` | Allocation line N error: all Batch rows rolled back |
| `T-ACID-14` | `S3-02` | `tests/test_nex_eos_mybee_voucher_fx_validation.py` | FX issue changed after review: block stale hash |
| `T-ACID-15` | `S5-02` | `tests/test_nex_eos_mybee_fx_remeasurement_pg.py` | FX snapshot correction after posting: immutable old journal |
| `T-ACID-16` | `S5-04` | `tests/test_nex_eos_mybee_journal_verification.py` | COMMITTED + verification failed: alert, no duplicate |
| `T-ACID-17` | `S5-02` | `tests/test_nex_eos_mybee_fx_remeasurement_pg.py` | repeat FX remeasure same period/source/hash: one adjustment |
| `T-ACID-18` | `S4-02` | `tests/test_nex_eos_mybee_journal_immutable_pg.py` | SQL UPDATE/DELETE original posted line must be denied |

### 7.3 E2E Acceptance — 12 immutable IDs

| ID | Primary packet | Proposed pytest | Must prove |
|---|---|---|---|
| `E2E-D04D12-FX-01` | `S8-03` | `tests/test_mybee_d04d12_fx_e2e.py` | approved USD shared purchase; 40/60 cost, FX snapshot, single POSTED GL |
| `E2E-D04D12-FX-02` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | USD AR settlement realized FX and source rate separate |
| `E2E-D04D12-FX-03` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | monetary close FX, nonmonetary excluded, tax valuation separate |
| `E2E-D04D12-01` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | KRW direct expense full business/accounting approval |
| `E2E-D04D12-02` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | shared payroll total, no private cost leakage |
| `E2E-D04D12-03` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | 120 purchased, 40/60 consumed, 20 inventory, P&L only expensed |
| `E2E-D04D12-04` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | partial invoice and concurrent allowance, no overconsumption |
| `E2E-D04D12-05` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | failure after partial GL line, rollback complete |
| `E2E-D04D12-06` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | duplicate human event not duplicate journal |
| `E2E-D04D12-07` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | P8 Golden A v1 unchanged and DRAFT-only |
| `E2E-D04D12-08` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | FX/rule change after review requires new approval |
| `E2E-D04D12-09` | `S8-04` | `tests/test_mybee_d04d12_domain_e2e.py` | salary privacy and cross-tenant P&L denial |

### 7.4 Negative cases required before M1 and M2

- M1: same person creates business request and approves accounting contrary to SoD → DENY; stale/revoked OA scope → DENY; fake company→Project shortcut → DENY.
- M1: candidate revision/hash change after approval → approval INVALID; no journal. Forged/expired proof → REJECT, no GL.
- M1: duplicate operation key with same payload → original result/no duplicate; same key different payload hash → CONFLICT; ACK-loss → authoritative reconciliation without double POSTED.
- M1: period not open, missing/invalid FX source or Snapshot → fail-closed; no arbitrary current web rate lookup at posting.
- M1: Project P&L unauthorized cross-company/project read, salary line leakage, unallocated/rounding mismatch, amount conservation violation → DENY/FAIL.
- M2: monetary foreign liability close/revaluation/settlement, reverse-and-repost, period close/Post race, non-monetary inventory vs expense, payroll privacy/grade risk, data-access race, migration idempotency, full 18/12 suite.

## 8. Codex handoff and implementation-first guardrails

### 8.1 First actionable PRs (start without new Repository creation)

| Order | Packet / PR target | Concrete deliverable | Minimum command/evidence |
|---|---|---|---|
| 1 | `S0-01` | Create read-only source manifest pinned to latest master; EOS DB/API/WA/WC/OA ownership and migration end-number | git SHA + git status + `docs/mybee_phase1/baselines/source_manifest.json` |
| 2 | `S0-02` | Run existing P8/Golden A v1 selected tests, signed wheel admission and no acceptance bypass | exact pytest/Quality Gate output; failures not auto-waived |
| 3 | `S0-03` | Install SRS 116 ↔ 37/13 packet manifest, blueprint source fingerprint and import/DSN guard | schema validation + 37/116 assertion, PDF gate pending |
| 4 | `MB0-01/MB0-02` | Create `domains/mybee/` package and contract lock without new Git repository | in-repo import lint, consumer negative contracts and test discovery |
| 5 | `MB1-01 / S1-01` | Publish MyBee FL revisioned catalog; add EOS legal entity/project-company schema after S0 approval | source file hash + guarded PostgreSQL test before business READY |

### 8.2 Codex mandatory packet prologue (copyable instruction)

```text
Read in this order:
  1. NeX Platform v2.1 Frozen (normative authority; do not amend)
  2. NeX–MyBee Phase-1 In-Repository Deferred EOS ADR v1.0
  3. NeX–MyBee EOS SRS v1.0 requirement IDs listed by this packet
  4. EOS ISP v1.0 + v1.1 preserved packet evidence and this v1.2
Before editing:
  - git status --short --branch; git rev-parse HEAD; inspect existing source
  - identify owner service/DB and proposed migration author
  - assert old Golden A/voucher-draft v1 semantics unchanged
  - list exact files and no private EOS/OA/WC DB import from domains/mybee
Implement small, gated provider/API code and the matching consumer contract tests.
Record a real test/PG/NSL/E2E artifact (or report BLOCKED, never claim PASS).
Merge only after required review/checkpoints. Do not create a permanent MyBee
branch or new EOS/MyBee repository. Do not edit frozen NSL compiler semantics.
```

### 8.3 PR and Gate evidence JSON envelope (PROPOSED schema, example values only)

```json
{
  "packet_id": "S4-03",
  "repository": "nurigitdev/2607_nex_platform",
  "target_branch": "master",
  "branch": "feat/eos/p1-s4-03",
  "base_sha": "<REAL_GIT_SHA_AT_START>",
  "head_sha": "<REAL_SHA_AFTER_IMPLEMENTATION>",
  "srs_ids": ["<EXACT_IDS_FROM_MATRIX>"],
  "migrations": [{"path": "database/nex-eos/migrations/2523_eos_posted_journal_posting.sql", "applied_test_db": false}],
  "gates": [{"name":"G-GL-ACID", "status":"NOT_RUN", "evidence_ref":null}],
  "golden_a_compatible": null,
  "code_owner_review": null,
  "production_activation": "DISABLED_UNTIL_ACCEPTED",
  "notes": "Never assert PASS without exact command, environment and result"
}
```

## 9. M2 Formal Closure and deferred EOS extraction review

M2 `DONE` requires every Phase-1 MUST requirement traced to code, API/DB schema, tests and immutable evidence; complete all original 37 packets and applicable 13 supplemental adjuncts; full Golden A/P8 compatibility; **all 18 real guarded PostgreSQL cases and all 12 protected E2E cases**; report eventual consistency watermark; OA/WC/NSL trust/SoD; posted GL conservation; FX historical market-reference source and company accounting/tax signoffs; purchasing stock consumption and payroll confidentiality; and D04 v1.9/D12 v2.8 PDF+DOCX text reconciliation signed off. Full Gate and independent finance owner approval precede production enablement.

When M2 is complete, hold `ADR-REVIEW-EOS-EXTRACT-P1`: compare measured EOS import dependencies, API compatibility, deploy/release coupling, security isolation, migration/replay outcomes, and actual MyBee/PA usage. Options remain Monorepo, MyBee-only extraction, EOS-only extraction, both. The decision gate is mandatory; extraction itself is NOT mandatory. Rollback of committed accounting is through governed reversal/fix-forward, not dropping posted records.

## 10. Open items, risk log and evidence status

| Risk or open item | Severity | Closure owner / evidence |
|---|---|---|
| Actual `master`/migration numbering may advance after the recorded SHA | High | S0-01 refresh SHA and check 2516..2527 before files written |
| Blueprint D04/D12 PDF body was not page-audited by prior GitHub text connector | High | S0-03 source provenance, finance owner page/section signoff before M2 |
| New MyBee domain root/install/coverage not present in current monorepo | Medium | MB0-01 implements package/build/test with clear import boundary |
| Actual Project Agent end-to-end lane may be incomplete despite existing delegated-work components | Critical | CP-M1-PA-WORK public API proof, not internal mock state |
| Journal Posting requires OA/WC evidence but cannot have cross-service ACID | Critical | S4-01..04 local EOS atomic commit and authoritative reconcile |
| M1 may be mistakenly marked complete from v1.1 S8 full dependency bypass | High | Explicit CP-M1 identifiers; S8-02, S8-03 and MB8-01 full remain M2 |
| Company FX trade-day reference and K-IFRS/tax policy not yet approved | High | Accounting officer release manifest + original source/session + rate lock |
| Unapproved feature flags or branch protection presumed active | High | S0 preflight, manual branch/ruleset check, default-off posting |
| Loss of Project P&L privacy / source double count | Critical | S6/S7 negative OA/GL eligibility/privacy and allocation conservation tests |

**Status:** Architecture/Slice sequencing drafted and static mapping verified. No actual source implementation, PostgreSQL run, PR/branch, admin protection configuration or accountant signoff was performed while producing v1.2. All implementation/production PASS statuses remain PENDING.

## Appendix A. Source provenance and exact SHA-256

| Input artifact | SHA-256 |
|---|---|
| `HISTORY/NeX_MyBee_D04_D12_EOS_ISP_v1.1_Repository_Ownership_Matrix.json` | `9a27702c030061bffd3e0f26b21569a6a2ab9be34ad1e08a4c4b737fc27a3664` |
| `NeX_MyBee_Phase1_InRepo_Deferred_EOS_ADR_v1.0.md` | `fe9ecc13921c9991c17ecb59dddb93ca5a5a3b488c12b7d2957ebe74a70c4136` |
| `NeX_MyBee_D04_D12_EOS_SRS_v1.0.md` | `7facf0620ce5e8b9d14c4a0c4895e6a2fb55e67edbe3578a6eb2536c661616fe` |
| `HISTORY/NeX_MyBee_D04_D12_EOS_Implementation_Slice_Plan_v1.1.md` | `a5f700a0595978b85e8c9e540f627af917f171735125d5fd619881cdac3adb50` |
| `NeX_MyBee_Phase1_InRepo_Ownership_Override_v1.0.json` | `7da02ab0e424468b663d7d9894750278546420d7875ce22115ef331385c0f94e` |
| `NeX_MyBee_D04_D12_EOS_Source_Audit_and_Gap_Analysis_v1.0.md` | `36b7d0ef6ce3582e787d24ca03cb2daa619885e66b6cf939e1dcc7cf278c48b9` |

Source reference links (read-only):

- [NeX Platform at pinned master](https://github.com/nurigitdev/2607_nex_platform/tree/5e64fb1f6b9af2198797d1bcdbc82e577b098fbe)
- [NeX EOS service source](https://github.com/nurigitdev/2607_nex_platform/tree/5e64fb1f6b9af2198797d1bcdbc82e577b098fbe/services/nex-eos/nex_eos)
- [EOS migration source](https://github.com/nurigitdev/2607_nex_platform/tree/5e64fb1f6b9af2198797d1bcdbc82e577b098fbe/database/nex-eos/migrations)
- [NeX development gates](https://github.com/nurigitdev/2607_nex_platform/blob/5e64fb1f6b9af2198797d1bcdbc82e577b098fbe/docs/development_process.md)
- [NSL Frozen/admitted source](https://github.com/nurigitdev/2608_nsl/tree/f5d899bb611ee2cd65ce9f6544ed6e51b450b7d4)
- [MyBee Blueprint D04/D12 source documents](https://github.com/nurigitdev/2611_MyBee_Blueprint/tree/948b50fd43fc4e0f0d3f40ffd6335871ec741559/docs/origin)

## Appendix B. Machine-readable v1.2 execution matrix

The companion JSON is `NeX_MyBee_Implementation_Slice_Plan_Execution_Matrix_v1.2.json`. It includes all 37 original packets with unique IDs and original SRS links, all 13 MB adjuncts rehomed to NeX, 7 M1 checkpoints, 116 per-requirement source/API/NSL/pytest/Gate mappings, 12 migration owners, 18 PostgreSQL fault cases and 12 E2E cases. It is a planning/traceability input to Codex, not runtime behavior or a completed test report.

