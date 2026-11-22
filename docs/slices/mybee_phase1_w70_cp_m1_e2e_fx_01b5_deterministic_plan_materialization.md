# CP-M1-E2E-FX-01B.5 Deterministic D12/D04 Plan Materialization

## Status

- Date: `2026-11-16`
- Status: `CLOSED`
- Parent work order:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Entry commit: `1d7298ab`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6`

This Slice converts the durable M1 WorkIntent and the hash-bound
`READY_FOR_D04` preparation checkpoint into the exact D12/D04 AgentPlan used
by the installed product runtime. It does not create a second planning store,
write directly to runtime tables, or grant authority to model output.

## Materialization Boundary

The preparation checkpoint now carries its complete immutable authority
projection in addition to its authority hash. The materializer verifies the
WorkIntent business-context hash, preparation and authority hashes, AE
AgentContext identity and Project lineage, and the exact installed capability
snapshot before it creates a plan.

The deterministic plan contains two ordered steps:

1. `S1` resolves to the exact signed `PROJECT.WORK_CODE.READ` D12 capability;
2. `S2` depends on `S1` and resolves to the exact signed governed D04 Journal
   posting capability.

D12 literals are limited to the authority-owned tenant, requester, Project,
and recognition date. D04 literals contain the exact EOS company,
VoucherCandidate version/revision/hash, and accounting-approval evidence from
the preparation checkpoint. No fixture, model-authored financial identifier,
or mutable display value is admitted.

The plan uses the existing AgentPlan validator and ExecutablePlan compiler.
Deterministic UUIDv5 identities bind execution ID and preparation hash, so an
identical replay produces identical plan, validation, executable plan, and
compiled step identities. The existing installed executor registry accepts
both compiled Skill bindings without a compatibility adapter.

## Fail-Closed Rules

Materialization fails before scheduling for malformed business context,
stale/tampered preparation or authority hashes, invalid D04 evidence hashes,
identity or Project-lineage mismatch, invalid execution ID or effective time,
missing or drifted installed capabilities, invalid capability snapshots, or a
non-VALID AgentPlan admission result.

The active AE module inventory is now `179` modules, with `169` active-product
modules and `72` modules in the active import graph. The MyBee service import
audit explicitly admits the new materializer. The protected P8-S62 actual
wheel smoke was reconciled from the retired NSL `0.2.0` expectation to the
repository-admitted NSL `0.2.1` baseline; its behavior and zero-residue
contract were not weakened.

## Verification

- Focused materializer tests: `15 passed`
- Materializer coverage: statement `100%`, branch `100%`
- Focused materialization/preparation/runtime/ownership regression:
  `78 passed`
- Actual PostgreSQL protected smoke: `4 passed`, no skip
  - AE/WC durable business-context persistence and replay;
  - EOS D12 WorkCodeSet immutability and zero residue;
  - OA Project entitlement restart decision and zero residue; and
  - admitted NSL `0.2.1` AE/EOS controlled WRITE, verification, and cleanup.
- Canonical AE Slice Gate: `6/6` commands passed
- AE regression: `6380 passed`, `47 skipped`
- Aggregate AE coverage: statement `96.48%`, branch `94.75%`
- Active-product coverage: statement `97.15%`, branch `95.06%`
- Contract validation:
  `269 schemas`, `319 examples`, `260 negative examples`, `10 OpenAPI`
- Golden journey, dependency, ownership, and quarantine audits: pass

The ordinary Slice Gate skips remain existing opt-in protected suites. The
four Slice-specific database paths above were enabled explicitly and executed
against the actual test databases.

## Closure Decision

`CP-M1-E2E-FX-01B.5` is closed. The authoritative M1 preparation can now be
compiled deterministically into the installed D12 READ followed by the D04
governed WRITE, while approval resume, verification, reconciliation, and
UNKNOWN handling remain owned by the existing product worker/runtime.
`CP-M1-E2E-FX-01B.6` may connect the resulting authority-backed transaction
to allocation, P&L, WA, and user-facing result delivery.
