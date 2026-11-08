# P8 Final As-Built Baseline and P9 Handoff v1.1

**Status:** FINAL / P8.10 CLOSED / DEMO RELEASE READY / P9 ENTRY AUTHORIZED

**Phase Closed:** P8 - Controlled WRITE / Approval / Delegation / Enterprise OS

**Amendment Closed:** P8.10 - Project Membership and Governed Project Operations

**Next Phase:** P9 - NeX-WA / Work Asset

**Observed Date:** 2026-10-25

**Platform Branch:** `transition/p4-agent-runtime-foundation`

## 1. Purpose

This document is the additive successor to
`P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.0.md`. The v1.0 file remains an
immutable historical record of the P8-S93 baseline. This v1.1 file closes the
P8-CA04 amendment after P8-S94 through P8-S103 and re-authorizes Demo Release
and P9 entry.

P8.10 adds Project membership, governed Project operations, canonical
operation naming, Project-aware Voucher access, and a protected demonstration
journey. It does not change the P8 v1.0 ownership, approval-domain,
exactly-once WRITE, reconciliation, verification, or attachment boundaries.

## 2. Verified Platform Baseline

The executable P8.10 baseline is the P8-S102 closure:

```text
repository = nurigitdev/2607_nex_platform
branch     = transition/p4-agent-runtime-foundation
commit     = 0106feba5617039751c13649529719ef0c297d6b
tree       = bb462992c5583879228feadc1b306371742767c5
contracts  = 5497f35ecacd65bfe608c2351ba4117cc7e2e64c
```

P8-S103 changes documentation only. Its closure commit is the Git commit
containing this document and is resolved from Git history to avoid embedding
a self-referential commit hash.

## 3. P8.10 Delivered Scope

P8.10 closed the following source-backed path:

```text
EOS Project membership persistence
-> idempotent membership lifecycle and last-active-OWNER protection
-> OA-authorized and EOS-membership-authorized Project API
-> canonical <DOMAIN>.<BUSINESS_OBJECT>.<ACTION> operation registry
-> exact-admitted Project READ and governed WRITE NSL Skills
-> AE deterministic Project intent clarification and admission
-> Project-membership-filtered Voucher CREATE / GET / LIST
-> actual PostgreSQL + live generation + authenticated browser journey
```

The canonical Project operation set is:

```text
PROJECT.PROJECT.CREATE
PROJECT.PROJECT.GET
PROJECT.PROJECT.LIST
PROJECT.PROJECT.DEACTIVATE
PROJECT.PROJECT_MEMBER.ADD
PROJECT.PROJECT_MEMBER.LIST
PROJECT.PROJECT_MEMBER.REMOVE
```

The canonical Voucher read set added by P8.10 is:

```text
FINANCE.VOUCHER_DRAFT.GET
FINANCE.VOUCHER_DRAFT.LIST
```

Legacy aliases are resolved before payload hashing and idempotency. They are
diagnostic compatibility inputs only and cannot create a second semantic
mutation or bypass approval.

## 4. NSL Runtime And Skill Admission

P8-S99A introduced the bounded NSL `OperationKind.UPDATE` contract and raised
the admitted runtime package from 0.2.0 to 0.2.1.

```text
repository          = nurigitdev/2608_nsl
runtime revision    = d53658ec2ab0b42e995fe0ebe80badd53218feec
runtime source tree = e16863f483bd6b9e2e1503de9baaf0f58cb15521
distribution        = nex-skill-language
package version     = 0.2.1
wheel               = nex_skill_language-0.2.1-py3-none-any.whl
wheel sha256        = sha256:a89ce5fde1a32749565ba0906a2f1faf1d440ff6db2dfc07c0b2a581378507cb
lock file sha256    = sha256:7efa6376602f1c89951657ba170a51ae7157189a0f46e607cebbb9ef949964ea
cryptography        = 46.0.7
```

The 0.2.0 lock remains immutable historical evidence. Platform startup admits
only the explicitly compatible 0.2.0 and 0.2.1 runtime identities. Project
and Voucher Skill artifacts introduced after the runtime release are admitted
independently by exact source revision, semantic hash, and manifest identity;
they do not rewrite the runtime wheel lock.

## 5. Ownership And Authorization

P8 v1.0 ownership remains unchanged. P8.10 adds these exact boundaries:

```text
OA   owns current identity, tenant authority, scopes, and revocation.
EOS  owns Project, Project membership, Voucher, BusinessOperation,
     idempotency, outbox, and business verification state.
AE   owns deterministic natural-language clarification and admitted Agent
     runtime intent/plan lineage; model output is never authority.
NSL  owns Skill semantics and controlled READ/WRITE execution contracts.
WC   retains approval and delegation coordination ownership.
```

Every governed Project or Voucher action requires fresh OA authority. Project
membership is checked independently at EOS and never substitutes for OA
authority. OA authority never substitutes for required Project membership.
The explicit finance-auditor scope may bypass membership for Voucher reads,
but cannot bypass tenant or active-Project isolation.

## 6. Persistence And Migration Baseline

P8.10 added one EOS-owned table, `eos_project_member`, through migration
`2514_eos_project_member`. No OA Project-membership table, cross-database
foreign key, or cross-service database mutation was added.

After the final protected journey, all seven actual service test databases
were compared read-only with their source migration inventories:

| Service | Source | Applied | Current head | Drift |
| --- | ---: | ---: | --- | --- |
| `nex-oa` | 18 | 18 | `1376_oa_trace_projection_index` | none |
| `nex-ag` | 20 | 20 | `1477_ag_platform_alert_persistence` | none |
| `nex-ae-api` | 60 | 60 | `2513_ae_voucher_attachment` | none |
| `nex-cx` | 23 | 23 | `1374_cx_trace_projection_indexes` | none |
| `nex-mo` | 10 | 10 | `1470_mo_model_rollout_persistence` | none |
| `nex-wc` | 13 | 13 | `1006_wc_approval_foundation` | none |
| `nex-eos` | 15 | 15 | `2514_eos_project_member` | none |

```text
source migrations  = 159
applied migrations = 159
missing             = 0
unexpected          = 0
```

The four P8 journey owners contain 134 public base tables after the additive
EOS table. The P8-S102 journey completed cleanup and reported zero matching
backend residue after Project, membership, authorization, Agent runtime,
approval, Voucher, and supporting lineage removal.

## 7. Contract Baseline

The P8.10 contract tree is
`5497f35ecacd65bfe608c2351ba4117cc7e2e64c`. Canonical validation passes:

```text
JSON schemas              = 197
positive examples         = 261
negative examples         = 224
OpenAPI documents         = 9
```

P8.10 adds versioned Project membership, Project operation, operation alias,
NSL artifact-admission, and Project-aware Voucher request contracts while
preserving all P8 v1.0 contract identities.

## 8. Protected Demonstration Acceptance

P8-S102 was re-run after the final Repository Full Gate with all protected
dependencies enabled:

```text
actual PostgreSQL         = OA / AE / WC / EOS
actual remote provider    = live generation
authenticated browser     = Chromium / Playwright
checks                    = 8 / 8 PASS
commit state              = COMMITTED
verification status       = VERIFIED
membership GET / LIST     = PASS
backend residue count     = 0
```

The live journey performed natural-language INTENT and PLAN generation and
then crossed admitted deterministic authority before controlled WRITE. The
provider never selected stable Project authority or bypassed clarification.

The browser acceptance proves actual OA login/session behavior, same-origin
AE routing, Chat submission/presentation, and logout. Its final Chat
projection routes are smoke-only views over the already-authoritative backend
result; P8.10 does not claim a new production Chat-to-Voucher public API.

The machine-readable protected report is local under the ignored `reports/`
tree and has SHA-256:

```text
sha256:5b698e4d3626956a4f242cb198d51e8cd89a1dda71d29264399d1e30e4c72b6b
```

It contains no raw prompt, credentials, database endpoint, provider endpoint,
cookie, or token material.

## 9. Repository Full Gate

P8-S103 executed the complete canonical Repository Full Gate before the final
protected acceptance rerun:

```text
collected tests       = 17,482
passed                = 17,365
protected skips       = 117
failed / errored      = 0 / 0
statement coverage    = 96.70% (required 96.00%)
branch coverage       = 96.09% (required 94.00%)
AE Web                = 377 passed / 0 failed
contract validation   = 197 / 261 / 224 / 9
```

```text
coverage JSON sha256 = 97b5247fdd0295266f7555b0a4b2c1a8ff024ca56e04de57459ec7118906e49a
JUnit XML sha256     = 09876ebc9ff640352f956b1bb12394bd8b1814927ee9da5b02f03ebfe5dbe3d8
```

Protected tests remain explicit environment guards in the ordinary Full Gate.
They are not treated as executed by that profile; P8-S102 was therefore run
independently after the Full Gate and supplied the actual DB/provider/browser
and zero-residue evidence in Section 8.

## 10. Closed P8.10 Invariants

1. New Skills, Tools, and public operation identifiers use exactly three
   canonical segments.
2. Existing P8 v1.0 execution and evidence lineage is unchanged.
3. Legacy aliases cannot duplicate mutation or bypass approval/idempotency.
4. Project creation and initial OWNER membership commit atomically.
5. An active Project cannot lose its last active OWNER.
6. Membership removal preserves durable audit and business lineage.
7. Cross-tenant Project and membership access fails closed.
8. Current OA revocation is honored before protected action.
9. OA authority and Project membership remain independent requirements.
10. Voucher CREATE, GET, and LIST are Project- and tenant-filtered at EOS.
11. Ambiguous natural-language Project identity never reaches governed WRITE.
12. Retry, restart, and replay produce at most one semantic mutation.
13. PostgreSQL migration, constraint, concurrency, and cleanup evidence passes.
14. The authenticated clean-bootstrap demonstration journey passes.
15. Repository coverage remains above the canonical 96% / 94% floor.

## 11. Deferred Scope

The P8 v1.0 deferred-scope ledger remains in force. P8.10 additionally does
not implement Project P&L, full ledger/accounting, bulk member administration,
complex Project hierarchy, Skill-pack packaging, or a production
Chat-to-Voucher public API. Those capabilities require explicit future design
and acceptance.

## 12. P9 Entry

P9 remains NeX-WA / Work Asset and is not a scheduler. P9 must preserve every
P8 v1.0 and P8.10 authority, tenant, Project membership, approval-domain,
exactly-once WRITE, reconciliation, verification, attachment, operation-name,
and evidence-lineage invariant.

P9 entry is authorized under the v1.0 Section 11 constraints, with this v1.1
document as the current P8 handoff baseline. P9 begins with a source-backed
current-state audit and ownership/contract extraction; it receives no implied
permission to mutate OA, AE, WC, EOS, or NSL-owned state directly.

## 13. Final Decision

```text
P8 v1.0 BASELINE PRESERVED
P8-CA04 CLOSED
P8.10 CLOSED
PROJECT MEMBERSHIP / GOVERNED PROJECT OPERATIONS CLOSED
PROTECTED DEMONSTRATION ACCEPTED
REPOSITORY FULL GATE PASSED
ZERO-RESIDUE CLOSURE PASSED
DEMO RELEASE ENTRY AUTHORIZED
P9 ENTRY AUTHORIZED
```
