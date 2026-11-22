# NeX MyBee M1 Final As-Built Baseline and W80 Handoff v1.0

**Status:** FINAL / W70 CLOSED / M1 CHECKPOINT ACCEPTED / W80 ENTRY AUTHORIZED

**Milestone Closed:** M1 - Early Integrated Vertical Slice

**Next Wave:** W80 - Journal Lifecycle, FX Settlement/Remeasurement, Period Close, and Reconciliation

**Observed Date:** 2026-11-22

**Platform Branch:** `codex/mybee-phase1-implementation`

## 1. Purpose

This document freezes the source-backed MyBee Phase-1 M1 baseline after the
public IA/PA journey, exact-head Repository Full Gate, and canonical release
set reconciliation. It records what is executable, which authorities own each
decision, what evidence passed, and what remains mandatory for M2.

M1 is an accepted integrated checkpoint. It is not the formal Phase-1 or M2
completion claim and does not silently close the full S8-02, S8-03, or MB8-01
packets.

## 2. Authority and Baseline Identity

The planning authority remains the frozen v1.2 Slice Plan and Execution
Matrix. W30 through W70 controlled amendments take precedence only for their
explicitly bounded corrections. This As-Built record does not rewrite those
requirements.

```text
repository               = nurigitdev/2607_nex_platform
branch                   = codex/mybee-phase1-implementation
product source commit    = 773769bafa2ac6680d3a775f81902a2e69103909
product source tree      = 823878f3a7fb90cfef96820398dbbb8a41ed9ef8
gate evidence commit     = 17c56322
live runtime commit      = 8f59e29ba0a04fa372c14e1df0c28cfc37331594
milestone scope          = M1_CHECKPOINT_ONLY
```

The product source commit contains the exact runtime and deployment content
used for the final nine-image release build. The later Gate evidence commit
adds documentation only. This As-Built commit is resolved from Git history to
avoid a self-referential identity.

The machine-readable handoff is
`docs/mybee_phase1/closure/w70_m1_final_asbuilt_w80_handoff.v1.json`.

## 3. Delivered Scope by Wave

| Wave | Delivered M1 boundary |
| --- | --- |
| W00 | Frozen source, repository ownership, compatibility, and regression baselines |
| W10 | LegalEntity/Project binding, approved COA and FX foundations, accounting periods, mandatory D12 WorkCodeSet, and Project work assignments |
| W20 | ApprovedDocumentEnvelope, Project/company-scoped approval, accounting Human SoD, approved-amount consumption, and proposal consumer |
| W30 | Immutable VoucherCandidate v2 revisions, accounting/FX/period/balance validation, and review/return/invalidate lifecycle |
| W40 | Project application and code lifecycle, Project entitlement synchronization, immutable PostedJournal, atomic posting, replay, outbox, and UNKNOWN recovery |
| W50 | Eligible POSTED source pools, approved allocation policy, deterministic allocation/reconciliation, and Project budget binding |
| W60 | Rebuildable Project P&L projection, labor/material attribution bridges, authorization, payroll privacy, and difference-attack guard |
| W70 | Canonical Tool contracts, signed D04/D12 Skill admission, installed PA/WC dispatch, controlled Journal execution, public M1 E2E, and exact-head release Gate |

## 4. Accepted M1 Journey

The accepted product path is:

```text
authenticated IA request
-> registry-selected Project Agent
-> WC route / assignment / claim / event delivery
-> live provider planning candidate
-> deterministic Product admission and executable plan
-> BUSINESS_FORMAL and accounting approvals with Human SoD
-> admitted D12 context and D04 governed WRITE
-> EOS VoucherCandidate and immutable PostedJournal
-> verified source pool and deterministic allocation
-> authorized Project P&L refresh/read
-> AgentResult publication and WA evidence settlement
```

All seven M1 checkpoints passed:

1. `CP-M1-PA-WORK`
2. `CP-M1-BUSINESS-PROOF`
3. `CP-M1-JOURNAL`
4. `CP-M1-PNL`
5. `CP-M1-S8-02`
6. `CP-M1-MB8-01`
7. `CP-M1-E2E-FX-01`

The journey used no direct runtime-transition SQL, manual domain transition,
M1-specific fixed Plan ID, tenant dictionary, or active Golden A fixture.

## 5. Service Authority Boundaries

| Authority | M1 ownership |
| --- | --- |
| OA | Human/service identity, roles, Project-Code entitlement, current authorization, token trust |
| AE | WorkIntent, planning/admission, Agent runtime jobs and steps, Product preparation, results, IA publication |
| WC | Delegation, routing, assignment, claim, Human approval, WorkResult/event delivery |
| EOS | Project/accounting business truth, approval proof, VoucherCandidate, PostedJournal, allocation, P&L projection |
| MO | Provider catalog, readiness, generation route, retry and telemetry boundary |
| WA | Post-work evidence and Work Asset settlement; not accounting or workflow authority |
| CX | Existing retrieval and grounding authority; not used to invent accounting authority |
| AG | Existing audit/operations authority; not a financial mutation authority |

No service may replace another service's authority with model output, cached
UI state, fixture data, or a direct cross-service database read.

## 6. Persistence and Migration Baseline

The exact live M1 acceptance applied all 210 current migrations across eight
isolated PostgreSQL schemas. The product source inventory remains 210:

| Service | Source count | Current head |
| --- | ---: | --- |
| `nex-oa` | 22 | `2519_oa_project_entitlement_inbox` |
| `nex-ae-api` | 64 | `2517_ae_product_preparation_resume` |
| `nex-cx` | 23 | `1374_cx_trace_projection_indexes` |
| `nex-mo` | 10 | `1470_mo_model_rollout_persistence` |
| `nex-ag` | 20 | `1477_ag_platform_alert_persistence` |
| `nex-wc` | 14 | `1007_wc_assignment_dispatch_scan` |
| `nex-eos` | 49 | `2548_eos_pnl_privacy_guard` |
| `nex-wa` | 8 | `2607_wa_service_logs` |

M1 final closure adds no migration. Posted Journal truth remains immutable;
correction is governed reversal/fix-forward work owned by W80.

## 7. Installed Runtime and Release Baseline

The canonical installed topology is:

```text
OCI artifacts          = 9
Compose services       = 18
installed processes    = 21
runtime environments   = 13
non-root images        = 9 / 9
entrypoint checks      = 12 / 12
registry push          = false
secret/DB URL rendered = false / false
```

Release identities:

```text
release-set digest = sha256:90b5903337e04b8d5b8b7e2394c4a1f0e77206463e4e00cb3d725d720e33cd5a
build-inputs digest = sha256:898a9a2de5ffe744e53dc222a3463d156000c5153eaf23d23be309fe65f7db03
NSL wheel version   = 0.2.1
NSL wheel digest    = sha256:a89ce5fde1a32749565ba0906a2f1faf1d440ff6db2dfc07c0b2a581378507cb
```

The installed release contains OA, AE, CX, MO, AG, WC, EOS, and WA runtimes
plus AE Web. It uses product processes and manifests, not P8 demo composition.

## 8. Protected Live Acceptance

The exact-source protected journey passed with:

- actual OA, AG, AE, CX, MO, WC, EOS, and WA PostgreSQL;
- actual OpenBao and RustFS;
- live Qwen3.5-9B generation at immutable revision
  `hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a` with reasoning disabled;
- authenticated Playwright;
- two non-identical transactions and three distinct Human principals;
- six approval decisions, two VoucherCandidates, two immutable Journals, and
  two allocation Batches;
- four P&L projections, two AgentResults, four acknowledged WA jobs, and four
  Work Assets;
- restart-safe result identity and no duplicate Journal, Batch, or result;
- eight isolated schemas removed and zero Compose residue.

The first allocation conserved `KRW 13,502,000.0000` as
`5,400,800.0000 + 8,101,200.0000` with zero residual.

## 9. Repository Quality Baseline

The exact-head canonical Full Gate passed:

```text
Python tests                    = 24,031
failures / errors               = 0 / 0
explicit protected skips       = 193
repository statement coverage  = 96.3353%
repository branch coverage     = 95.3119%
product statement coverage     = 98.2666%
product branch coverage        = 96.7614%
contracts                      = 274 / 320 / 260 / 10
```

Protected runners requiring explicit credentials or database/live opt-in were
not reclassified as pass by the default Full Gate. Their accepted M1 evidence
is the separate exact-source protected journey in Section 8.

## 10. Frozen M1 Invariants

1. The generation provider proposes semantics but never grants identity,
   approval, accounting, Project, or mutation authority.
2. Public Product dispatch is registry-driven and scenario-neutral.
3. Project UUID is an internal FK; user-facing accounting resolves and
   communicates by approved Project Code.
4. Every M1 accounting document, Candidate, Journal line, allocation, and P&L
   result preserves mandatory Project attribution and lineage.
5. The requester, business approver, and accounting approver remain distinct
   where SoD requires it; self-approval is denied.
6. VoucherCandidate is pre-posting truth. PostedJournal is immutable GL truth.
7. Posting and approval consumption are atomic inside one EOS transaction.
8. UNKNOWN commit state is reconciled against EOS before retry.
9. Allocation conserves source amounts and cannot double count direct and
   allocated recognition.
10. Project P&L is a rebuildable read projection with authorization,
    watermark, classification, and payroll privacy guards.
11. WA stores post-work evidence and cannot become workflow or accounting SoR.
12. Replay, restart, ACK loss, and expired-lease recovery cannot create a
    second Journal, allocation Batch, or AgentResult.
13. Runtime fixtures may seed pre-request business data only; they cannot
    perform product transitions.
14. No direct cross-service database read or write is admitted.
15. M1 checkpoint acceptance does not imply M2 completion.

## 11. Explicit M2 Deferred Scope

The following remain open and mandatory:

| Wave | Deferred packets and obligation |
| --- | --- |
| W80 | `S5-01..04`: reversal, FX settlement/remeasurement, period close/Post concurrency, full Journal verification/reconciliation |
| W81 | `S6-04`, `MB6-01`, `MB6-02`: generic source intake and payroll/purchasing adapters |
| W84 | `S7-04`, `MB1-04`, `MB7-01`: NVT roll-up, Project close, grade policy, read-only P&L UX/privacy |
| W90 | full `S8-02`, full `S8-03`, full `MB8-01`: certified Tool/Skill and complete runtime closures |
| W93 | `S8-04`: payroll, inventory, FX-close protected E2E matrix |
| W99 | `S8-05`, `MB8-02`: 116 SRS, 18 guarded PostgreSQL faults, 12 E2E, finance/source signoff, release closure |

M1 does not claim finance-owner PDF/source signoff, production enablement,
complete FX lifecycle, full inventory/payroll intake, or formal Phase-1 closure.

## 12. W80 Entry Handoff

W80 entry is authorized, but implementation must begin with a source-backed
`W80-CA01: M1-to-M2 Journal Lifecycle Entry Reconciliation` rather than
starting `S5-01` from assumptions. The entry review must freeze:

1. reversal versus destructive Journal mutation boundaries;
2. monetary versus non-monetary FX position classification;
3. settlement, remeasurement, realized/unrealized gain-loss, and rate lineage;
4. OPEN/CLOSING/CLOSED period transitions and concurrent Post/Close behavior;
5. Candidate, Journal, reversal, outbox, reconciliation, allocation, and P&L
   downstream lineage;
6. existing API/table reuse and the minimum migration sequence;
7. protected PostgreSQL, replay, restart, UNKNOWN, and zero-residue gates.

W80 must preserve all M1 authority, SoD, immutable GL, exactly-once,
allocation-conservation, Project attribution, privacy, and fixture-retirement
invariants. No M1 compatibility path may be removed merely to simplify W80.

## 13. Final Decision

```text
W00 THROUGH W70 M1 SCOPE COMPLETE
SEVEN M1 CHECKPOINTS PASS
PUBLIC IA/PA PRODUCT JOURNEY PASS
ACTUAL EIGHT-DATABASE PROTECTED ACCEPTANCE PASS
LIVE QWEN3.5-9B AND PLAYWRIGHT PASS
REPOSITORY FULL GATE PASS
NINE-IMAGE RELEASE SET RECONCILED
ZERO-RESIDUE CLOSURE PASS
W70 M1 FINAL AS-BUILT FROZEN
M2 REMAINS OPEN
W80 ENTRY AUTHORIZED THROUGH W80-CA01
```
