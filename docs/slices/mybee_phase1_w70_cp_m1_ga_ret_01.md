# CP-M1-GA-RET-01: Golden A Selection Freeze and Retirement Preparation

## Status

- Slice: `CP-M1-GA-RET-01`
- Status: `CLOSED`
- Decision authority: `W70-CA02`
- Implementation date: `2026-11-15`
- Database migration: none
- Remote provider: not required

## Scope

This Slice freezes Golden A for every new public IA selection while retaining
the existing registry, Skill, runtime handler, and evidence assets for bounded
rollback and historical replay until `CP-M1-GA-RET-02`.

The implementation does not delete the voucher-draft EOS API, mutate an
immutable registry or bundle, or terminate an existing execution. It separates
new-selection authority from replay execution authority.

## Implemented Boundary

1. Added the immutable
   `ae.product_capability_retirement_projection.v1` contract and loader.
2. Covered both the installed v1 registry and the signed MyBee M1 checkpoint
   registry without rewriting either registry.
3. Marked `FINANCE.CREATE_VOUCHER_DRAFT`,
   `FINANCE.VOUCHER_DRAFT.CREATE`, `FINANCE.VOUCHER_DRAFT_CREATE`, and
   `createEosVoucherDraft` as `REPLAY_ONLY` with `new_selection=DENY`.
4. Removed the retired registration from every newly constructed capability
   selection view and removed its domain activator from the public planning
   registry.
5. Added an INTENT-stage guard before private candidate storage and evidence
   persistence. A newly generated retired intent fails with
   `CANDIDATE_CAPABILITY_RETIRED`, so no WorkIntent, AgentPlan, ExecutablePlan,
   or RuntimeJob can follow it.
6. Preserved existing persisted candidate replay and the installed worker
   consumer through an explicit `include_replay_only=True` composition used
   only for drain/reconciliation.
7. Added the retirement projection to canonical Compose and the AE runtime OCI
   image. A canonical runtime without this projection fails closed.
8. Added deterministic build/check tooling for the reference inventory,
   rollback receipt, and selection-freeze projection.

## Immutable Evidence

| Artifact | Purpose |
| --- | --- |
| `deployment/retirement/golden-a-reference-inventory.v1.json` | Classifies every detected Golden A reference as `GENERALIZE`, `REMOVE_ACTIVE`, `REPLAY_ONLY`, or `HISTORY` |
| `deployment/retirement/golden-a-rollback-receipt.v1.json` | Freezes the last-known-good registry, bundle, deployment, runtime, and evidence hashes |
| `deployment/retirement/golden-a-selection-freeze.v1.json` | Enforces the public new-selection denial and in-flight drain policy |

The rollback receipt expires at `2027-02-13T23:59:59Z` and is invalidated
earlier by `CP-M1-GA-RET-02`. It explicitly prohibits new product selection.

## Verification

### Static and unit regression

```text
focused impacted regression: 236 passed
MyBee Phase 1 regression: 785 passed, 1 protected smoke skipped
AE Slice Gate: 5,938 passed, 46 protected smoke skipped
AE Slice Gate coverage: statement 96.18%, branch 94.25%
retirement artifact check: PASS
retirement selection Gate: PASS
classified Golden A reference paths: 206
retirement product module coverage: statement 100%, branch 100%
public activator composition coverage: statement 100%, branch 100%
contract / Golden Journey / dependency audits: PASS
```

The tests cover malformed projections, uncovered registries, aliases,
canonical configuration omission, public-selection denial, replay-only
activation, pre-storage INTENT rejection, and persisted candidate replay.

### Actual PostgreSQL protected smoke

Target:

```text
database = nex_ae_test
role     = nex_ae_user
mode     = read-only lineage inspection
```

Result:

```text
database identity                 = PASS
runtime tables present            = PASS
Golden A lineage executions       = 0
in-flight Golden A executions     = 0
runnable Golden A runtime jobs    = 0
zero mutation                     = PASS
```

Evidence is written to
`reports/smoke/mybee-w70-ga-ret-01-postgres.json` with the database password
redacted.

## Closure

```text
new Golden A public selection       = DENIED
new Golden A capability snapshot    = EXCLUDED
new Golden A semantic admission     = BLOCKED BEFORE PERSISTENCE
historical candidate replay         = AVAILABLE
installed in-flight execution path  = AVAILABLE FOR DRAIN ONLY
immutable registry/bundle/evidence  = PRESERVED
in-flight PostgreSQL lineage        = DRAINED
CP-M1-GA-RET-01                     = CLOSED
```

The next implementation boundary is
`CP-M1-E2E-FX-01A.1: Source/refactoring checkpoint, data-origin matrix,
residue baseline, and exact installed composition map`.
