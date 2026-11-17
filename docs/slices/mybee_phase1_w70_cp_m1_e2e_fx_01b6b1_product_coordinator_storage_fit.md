# CP-M1-E2E-FX-01B.6B.1 Product Coordinator Contract and Storage-Fit Audit

## Status

- Date: `2026-11-17`
- Status: `CLOSED_WITH_STOP_DECISION`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_Installed_M1_Preparation_and_Deterministic_Plan_Activation_Closure_v1.0.md`
- Entry commit: `abaa7083`
- Database migration: none
- Database contacted: no
- Remote provider: not required
- Next boundary:
  `CP-M1-E2E-FX-01B.6B.1A Durable Product Preparation Checkpoint and Approval Event Persistence Decision`

This Slice freezes the generic product-planning coordinator contract, admits
the MyBee M1 contract through the existing immutable Product Capability
Registry, and audits whether current AE persistence can durably represent the
two pre-plan approval waits and deterministic plan activation.

It intentionally does not activate M1 coordination. The source-backed audit
found that the current persistence model cannot represent those waits without
changing the meaning of existing WorkResult or NSL approval structures.

## Product Coordinator Contract

`ProductPlanningCoordinatorRegistry` now provides:

- exact capability ID, version, and registration-hash selection;
- immutable coordinator identity and semantic registration hash;
- explicit `CONTRACT_ONLY` and `ACTIVE` activation states;
- exact required Product Capability bindings;
- immutable preparation-adapter and materializer source identities;
- initial, waiting, ready, and terminal state vocabulary;
- required owner-service operations; and
- capability-drift and inactive-registration rejection.

The generic protocol owns only `begin`, `resume`, and `materialize` boundaries.
It does not know a tenant, company, Project, amount, currency, FX rate,
account, allocation ratio, approval ID, or scenario value.

The M1 registration is the first contract:

```text
coordinator       = MYBEE.M1.TRANSACTION_PREPARATION
trigger           = FINANCE.VOUCHER.APPROVE_AND_POST@1.0.0
required READ     = PROJECT.WORK_CODE_SET.GET@1.0.0
initial           = PREPARATION_PENDING
wait 1            = WAITING_BUSINESS_APPROVAL
wait 2            = WAITING_ACCOUNTING_APPROVAL
ready             = READY_FOR_D04
activation        = CONTRACT_ONLY
```

The registration binds the exact Product Capability registration hashes, M1
preparation-registry source identity, and M1 deterministic materializer source
identity. It is not selected by prompt text, tenant dictionaries, fixture
values, or a scenario-name conditional.

## Source-Backed Storage-Fit Decision

The executable audit is:

```text
scripts/quality/run_mybee_w70_cp_m1_e2e_fx_01b6b1_storage_fit_audit.py
```

Its decision is:

```text
audit_status           = PASS
storage_fit            = NOT_FIT
entry_decision         = STOP_FOR_CONTROLLED_PERSISTENCE_DECISION
coordinator_activation = CONTRACT_ONLY
```

### Reusable Foundations

| Existing structure | Decision | Condition |
| --- | --- | --- |
| WorkIntent and AgentContext | reuse | remain immutable business-context lineage |
| Semantic candidate evidence | reuse | provider PLAN remains non-authoritative evidence |
| AgentPlan and ExecutablePlan | conditional reuse | final deterministic plan must remain the first executable plan until version policy is explicit |
| Existing scheduler and worker | reuse later | only after the complete deterministic plan is durable |

### Structures That Are Not Semantically Fit

| Existing structure | Finding |
| --- | --- |
| `ae_wait_registration` | requires an existing ExecutableStep and permits only `WORK_RESULT` or `NSL_APPROVAL` |
| `ae_external_event_inbox` | permits only `WORK_RESULT_SUBMITTED` or `NSL_APPROVAL_DECIDED` and enforces their domain-specific field shapes |
| `ae_step_result` | requires an existing ExecutablePlan and ExecutableStep, so it cannot own a pre-plan checkpoint |
| `ae_runtime_job.payload_json` | mutable delivery state without typed checkpoint version, hash, coordinator identity, or approval authority |

BUSINESS_FORMAL and accounting review cannot be relabeled as WorkResult or
NSL_WRITE approval. A WC event-delivery ACK is not approval authority, and a
provider candidate is not an owner-service checkpoint. Reusing any of those
columns would violate the parent amendment's semantic-reuse rule.

## AgentPlan Version Finding

Current background planning calls
`DeterministicCandidateAdmissionService.admit_and_compile()` directly, while
the M1 materializer currently emits AgentPlan version `1`.

The safe current policy is therefore:

```text
provider PLAN = immutable semantic evidence only
final READY_FOR_D04 plan = first executable AgentPlan
```

Persisting the provider PLAN as executable AgentPlan version `1` and later
trying to replace it with the deterministic financial plan is not admitted.
The follow-up decision must either preserve the evidence-only policy or define
an explicit, immutable multi-plan version transition. It may not overwrite
the provider or deterministic plan.

## Anti-Fixture Guard

The contract and M1 registration contain no fixed:

- tenant or company;
- Project identity or count;
- amount or currency;
- FX rate;
- account;
- approval or evidence ID;
- allocation ratio;
- Golden A or Demo runtime branch.

Tests cover multiple capability IDs and versions, exact hash drift, duplicate
registration, inactive admission, malformed state vocabularies, missing
capabilities, and repository source drift. Product business values remain in
persisted input, owner-service authority, or admitted Product configuration.

## Required Follow-Up Decision

`CP-M1-E2E-FX-01B.6B.2` is not admitted yet. A short controlled decision,
`CP-M1-E2E-FX-01B.6B.1A`, must first define the smallest durable correction
covering:

1. a typed, immutable, versioned product-preparation checkpoint;
2. typed BUSINESS_FORMAL and accounting-approval event admission;
3. exact AgentExecution, WorkIntent, AgentContext, capability, and coordinator
   lineage;
4. idempotent event ACK-loss and restart resume binding; and
5. the final deterministic AgentPlan version policy.

This Slice does not authorize a table, column, wait type, event type, or
migration. The follow-up must compare a dedicated preparation-checkpoint
store with a constrained extension of current wait/inbox structures and select
the option that preserves ownership and semantics with the smallest blast
radius.

## Verification

- Focused coordinator and audit regression: `8 passed`
- New coordinator modules: statement `99%`, branch `100%`
- Executable storage-fit audit: `PASS`
- Storage decision: `NOT_FIT`
- Fixture business-value residue: `0`
- Related ownership and static-guard regression: `36 passed`
- AE Slice Gate: `6524 passed`, `47 skipped`
- AE statement coverage: `96.45%` (threshold `95.00%`)
- AE branch coverage: `94.65%` (threshold `94.00%`)
- Contract validation: `PASS` (`272` schemas, `320` examples,
  `260` negative examples, `10` OpenAPI documents)
- AE coverage ownership: `PASS` (`184` modules, `95` in the active graph,
  `174` active product modules)
- Database contact: none
- Remote provider contact: none
- Database migration: none

Machine-readable evidence is written to:

```text
reports/quality/mybee-w70-cp-m1-e2e-fx-01b6b1-product-coordinator-storage-fit.json
reports/quality/mybee-w70-cp-m1-e2e-fx-01b6b1-ae-slice-gate.json
```

## Closure Decision

`CP-M1-E2E-FX-01B.6B.1` is closed with a mandatory stop decision. The generic
coordinator contract and M1 exact-capability registration are ready, but the
M1 coordinator remains `CONTRACT_ONLY`.

Implementation must not continue to `6B.2` until `6B.1A` selects and authorizes
a semantically correct durable preparation and approval-event boundary.
