# P8 Final As-Built Baseline and P9 Handoff v1.0

**Status:** FINAL / P8 CLOSED / GOLDEN A CLOSED / RELIABILITY CLOSED / P9 ENTRY AUTHORIZED

**Phase Closed:** P8 - Controlled WRITE / Approval / Delegation / Enterprise OS

**Next Phase:** P9 - NeX-WA / Work Asset

**Observed Date:** 2026-10-24

**Platform Branch:** `transition/p4-agent-runtime-foundation`

## 1. Purpose

This document freezes the source-backed P8 as-built baseline after P8-S93. It
does not reopen P8 design. P9 may extend this baseline only additively and must
preserve the ownership, authority, identity, approval, WRITE, reconciliation,
verification, and evidence boundaries recorded here.

## 2. Final Baseline Identity

The final verified P8 runtime and acceptance baseline is the P8-S92 closure:

```text
repository = nurigitdev/2607_nex_platform
branch     = transition/p4-agent-runtime-foundation
commit     = 89f70d742d7ff40f01a990729499ad875ae88bf1
tree       = 8a375453925ebf228a64e61b6c79e05d8f87701d
contracts  = d889cf34cdf9fa92b6ce5894a9ddb0a061100034
```

The S92 Golden A package was re-run after that commit and binds directly to
the commit and tree above. P8-S93 changes documentation only.

The P8-S93 closure commit is the Git commit containing this document. It is a
verified descendant of the runtime baseline above and is resolved from Git
history or an external release attestation; no document can safely embed its
own changing commit hash.

## 3. Closed Objective

P8 delivered the first authoritative business WRITE path:

```text
authenticated IA request
-> deterministic planning admission
-> admitted NSL v0.2 execution
-> NSL_WRITE approval and durable WAIT
-> exact ResumeToken / resume authority
-> RuntimePolicy / WriteGuard
-> durable idempotency and WRITE_REQUESTED evidence
-> EOS FINANCE.CREATE_VOUCHER_DRAFT
-> COMMITTED / NOT_COMMITTED / UNKNOWN_COMMIT_STATE
-> authoritative reconciliation when required
-> post-WRITE verification
-> durable Agent result lineage
```

P8 also delivered bounded WC delegation, owner-private Voucher evidence
attachments, IA approval UX, and a distinct EOS-owned `BUSINESS_FORMAL`
multi-stage approval lifecycle.

## 4. Final Ownership And Authority

```text
NSL     owns deterministic Skill semantics, ApprovalRequest, ResumeToken,
        WRITE coordination contracts, and verification contracts.
AE      owns Agent runtime, exact protected NSL request bytes, waits, resume
        admission, Platform ApprovalEvidence, WRITE evidence, IA facade, and
        owner-private Voucher attachment batches/manifests.
WC      owns WorkItem/Claim/Assignment delegation coordination and human
        ApprovalWorkItem/Decision/Event/Outbox workflow state.
OA      owns identity, membership, service trust, and current authorization.
EOS     owns organization, NVTProject/Project/Account, BusinessOperation,
        idempotency, VoucherDraft, formal approval, outbox, reconciliation,
        and business verification state.
RustFS  owns private attachment object bytes; EOS receives only admitted
        metadata and opaque object references.
MO      owns model/provider routing and readiness; model output is never
        execution or approval authority.
AG      consumes redacted operational and audit projections only.
IA      is an authenticated interaction surface, not an authority or SoR.
```

Cross-service integration uses authenticated contracts and service APIs. P9
must not introduce direct cross-service table mutation as a shortcut.

## 5. Persistence And Migration Baseline

P8-S90 freshly recreated and migrated the four P8 owner databases and proved
their complete 133-table state returned to the fresh baseline after protected
acceptance. P8-S93 then compared every source migration with every applied
`schema_migrations` row across all seven current service databases:

| Service | Source migrations | Applied migrations | Current head | Drift |
| --- | ---: | ---: | --- | --- |
| `nex-oa` | 18 | 18 | `1376_oa_trace_projection_index` | none |
| `nex-ag` | 20 | 20 | `1477_ag_platform_alert_persistence` | none |
| `nex-ae-api` | 60 | 60 | `2513_ae_voucher_attachment` | none |
| `nex-cx` | 23 | 23 | `1374_cx_trace_projection_indexes` | none |
| `nex-mo` | 10 | 10 | `1470_mo_model_rollout_persistence` | none |
| `nex-wc` | 13 | 13 | `1006_wc_approval_foundation` | none |
| `nex-eos` | 14 | 14 | `2513_eos_voucher_attachment_lineage` | none |

```text
source migrations  = 158
applied migrations = 158
missing             = 0
unexpected          = 0
```

The read-only S93 comparison used the actual service-owned `_test` databases.
P9 migrations must remain service-local and must preserve every P8 head as an
immutable historical prefix.

## 6. Contract Baseline

The final P8 contract tree is
`d889cf34cdf9fa92b6ce5894a9ddb0a061100034`. The canonical validator passes:

```text
JSON schemas                              = 191
indexed positive examples                 = 255
indexed negative examples                 = 221
OpenAPI documents                         = 9
canonical reference checks                = 1,050
producer/consumer and operation parity    = 25
terminology checks                        = 21
```

P8-owned public contract families are frozen at:

```text
WC delegation:
  DelegationSpec 1.1
  wc_delegation_policy.v1
  wc_delegation_lineage.v1

WC approval:
  wc_approval_work_item.v1
  wc_approval_decision_request.v1
  wc_approval_decision.v1
  wc_approval_event.v1
  wc_approval_inbox.v1
  wc_approval_gate_detail.v1
  human_gate_view.p8.v1
  business_formal_gate_view.p8.v1

AE attachment:
  ae_voucher_attachment_batch.v1
  ae_voucher_attachment_manifest.v1
  ae_voucher_attachment_resolution.v1

EOS WRITE and formal approval:
  eos_create_voucher_draft_command.v1
  eos_create_voucher_draft_result.v1
  eos_approver_resolution_request.v1
  eos_approver_resolution.v1
  eos_approval_policy.v1
  eos_approval_instance.v1
  eos_approval_stage.v1
  eos_approval_proof.v1
  eos_voucher_verification.v1
```

The relevant OpenAPI baselines are:

```text
NeX AE API                         = OpenAPI 3.1.0 / 1.7.0
NeX Work Coordination API         = OpenAPI 3.1.0 / 2.1.0-p8-s41
NeX Enterprise Operations System  = OpenAPI 3.1.0 / 2.1.0-p8-s39
```

Schema and OpenAPI version labels are contract identities, not permission to
collapse approval domains or change runtime semantics without a new closure.

## 7. Admitted NSL v0.2 Baseline

```text
repository          = nurigitdev/2608_nsl
source revision     = c0a8d4e125ee129c4556d896356237bb3973582d
source tree         = 057611c8c584afa5483f7f3e5990a19533ddea58
source worktree     = clean / master aligned with origin/master
distribution        = nex-skill-language
package version     = 0.2.0
wheel               = nex_skill_language-0.2.0-py3-none-any.whl
wheel sha256        = sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
lock schema         = nsl_wheel_lock.v2
lock sha256         = sha256:1bf3bee5cf0f921d1d125fe9cd61f61e9405453d61bd448fb8e5655b830f9a66
release admission   = sha256:048e8cc8603ce4fba4ffd5d1f482bdd1444f9061122e221b851fc197c6959b84
cryptography        = 46.0.7
```

Platform code consumes admitted public NSL APIs. It does not redefine private
NSL semantics, and an unknown runtime profile fails closed.

## 8. Final Acceptance Evidence

| Gate | Accepted evidence |
| --- | --- |
| Contract hygiene | `191 / 255 / 221 / 9`; 1,050 reference, 25 parity, 21 terminology checks |
| Full repository regression | `17,238 passed / 111 protected skips / 0 failed` |
| Coverage | statement `96.72%` / branch `96.11%`; required `96% / 94%` |
| Actual PostgreSQL | `74 passed / 0 skipped`; 105 P8-owner migrations; 133 table fingerprints; zero residue |
| IA Playwright | `4 passed / 0 skipped`; AE Web `375 passed`; desktop/mobile overflow 0; zero residue |
| Live provider preflight | embedding, reranking, and generation all `PASS` |
| Golden A final re-run | actual PostgreSQL/provider; `COMMITTED`; `VERIFIED`; one mutation; zero residue |
| Fault final re-run | `13 passed / 0 skipped`; S76-S86 matrix; zero final DB/object residue |

The final Golden A package binds to the exact Platform baseline in Section 2:

```text
package digest            = sha256:3af8aea41d52883807440df4c12761bcfa6fe81f215bce3f1a32bccccf9c850e
protected evidence digest = sha256:a57656b3edd6d3bac4211988c0e207d94051c94e18e983d634bd6cd56d9c13af
full gate evidence digest = sha256:0b3e58341d287cc2790b107d1cb7870484a3c39673422f951e990ed286db6c69
```

The S92 rerun explicitly supplied the canonical S89 JUnit and coverage paths;
the historical `reports/coverage/*` default was not accepted as the final P8
coverage identity.

## 9. Closed Invariants

1. LLM output is an untrusted candidate and never execution authority.
2. `NSL_WRITE`, `BUSINESS_FORMAL`, and `AGENT_FORMAL` remain distinct.
3. Approval resume requires the exact admitted request, decision, evidence,
   checkpoint, and token lineage.
4. Current OA trust and authorization are checked at each protected action.
5. One semantic command creates at most one EOS business mutation.
6. `UNKNOWN_COMMIT_STATE` is reconciled; it is never blindly retried as a new
   WRITE and never silently converted to `NOT_COMMITTED`.
7. A committed WRITE is not recreated when verification fails or is unknown.
8. Attachment bytes remain owner-private; the approved immutable manifest is
   bound to the command and EOS stores opaque references only.
9. Tenant, owner, approval, payload, and attachment tamper fail closed.
10. WorkItem existence and routing do not grant Claim or execution authority.
11. P8 state survives retry/restart without duplicate approval, resume,
    Voucher, outbox event, object, or result semantics.

## 10. Deferred Scope Ledger

The following remain explicitly outside the P8 baseline:

```text
NVT token economics and incentive calculation
full financial ledger / project P&L
procurement and fiscal close
attachment content approval-manifest policy
OCR, receipt extraction, contract summarization, ZIP inspection, CX ingestion
full RustFS document lifecycle and external malware scanner operation
email/push approval and external notification delivery
ActingAuthority
bulk controlled WRITE
complex quorum and parallel approval stages
multiple NSL WRITE nodes in one execution
EOS service decomposition / multi-host HA
```

These items require explicit future requirements and acceptance. They must not
be smuggled into P9 Work Asset implementation.

## 11. P9 Entry Scope

The Frozen baseline defines P9 as:

```text
NeX-WA = Work Asset / Post-work Activity / Reporting
NeX-WA != Scheduler
```

The initial P9 source set is the Frozen Work Asset and Work Activity / Periodic
Reporting design. Schedule and recurring work remain WC capabilities and are
not transferred to WA.

P9 entry is authorized subject to these invariants:

1. Begin with a source-backed P9 current-state audit and contract extraction;
   do not implement directly from legacy archives.
2. WA consumes acknowledged post-work outcomes through authenticated,
   idempotent contracts; it does not directly query or mutate AE, WC, or EOS
   owned tables.
3. Required WC WorkResult/ResultDelivery acknowledgement remains the Agent
   completion boundary. Optional WA publication cannot block or redefine it.
4. WA owns post-work assetization, activity, effort/labor allocation, and
   reporting projections only. It does not own Schedule, Claim, AgentExecution,
   Approval, or business transaction authority.
5. Preserve tenant, actor, WorkItem/Claim, AgentExecution/ResultDelivery,
   Project, BusinessOperation, Voucher, approval, evidence, and trace lineage.
6. OA remains the authorization authority; WC remains work coordination and
   schedule SoR; AE remains Agent runtime; EOS remains business SoR.
7. P8 approval-domain separation, exactly-once WRITE, reconciliation,
   verification, and private attachment boundaries are immutable inputs.
8. Decide P9 service/database ownership and retention before adding tables.
   Reusing an existing owner by convenience is not an accepted decision.
9. Additive P9 migrations and contracts must preserve the P8 migration and
   contract prefixes in Sections 5 and 6.
10. Every P9 gate must retain the repository `96% / 94%` coverage floor and
    protected PostgreSQL/authorization/tenant/restart evidence appropriate to
    its risk.

`P9 ENTRY AUTHORIZED` authorizes the P9 design closure and implementation
sequence under these constraints. It does not pre-authorize a WA ownership or
API design that has not yet passed source-backed review.

## 12. Final Decision

```text
P8 CLOSED
P8 GOLDEN A CLOSED
P8 RELIABILITY CLOSED
P8 CONTRACT / DATABASE / UI GATES CLOSED
P9 ENTRY AUTHORIZED
```

P9 must treat this document and its verified descendant closure commit as the
P8 handoff baseline.
