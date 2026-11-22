# CP-M1-E2E-FX-01B.6B.1A.4 Product Coordinator Registration and Compatibility Closure

## Status

- Date: `2026-11-17`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Migration: none
- Actual database: `nex_ae_test`
- Remote provider contacted: no
- Successor: `CP-M1-E2E-FX-01B.6B.2`

## Implemented Boundary

This Slice closes the registration fields required by the `6B.1A` persistence
decision before any Product Coordinator activation.

- Product Coordinator registration and registry contracts advance to schema
  version `v2`.
- The generic immutable registration now hash-binds:
  - Product Preparation checkpoint schema version;
  - structured exact-replay, semantic-drift, stale-event, and ACK-loss policy;
  - supported executor kinds; and
  - exact installed Skill bundle locks.
- Each Skill lock binds capability ID/version/registration hash, bundle ID and
  manifest reference, Skill ID/version, and Skill semantic hash.
- Skill locks are derived from already validated Product Capability Registry
  entries. Runtime code contains no fixed tenant, Project, financial value, or
  copied test fixture.
- The M1 coordinator advances from version `1.0.0` to `1.1.0`, and its registry
  advances from version `1` to `2` so the hardened contract cannot be confused
  with the earlier contract-only shape.
- M1 remains `CONTRACT_ONLY`; no Product handler, worker, scheduling path, or
  business mutation is activated by this Slice.
- Existing WorkResult and NSL approval wait/event/resume behavior remains
  unchanged and compatible.

## Immutable Registration Evidence

```text
coordinator_id      = MYBEE.M1.TRANSACTION_PREPARATION
coordinator_version = 1.1.0
registration_hash   = sha256:671926c6cb641cf19659be7a9bde00104b5c671b6c0aaffc2bd2ea6994886345
registry_version    = 2
registry_hash       = sha256:ff727803dbb6a4ad0f019c0131ff3a0c2b61c25a565393987a5adb55c7521be7
activation_status   = CONTRACT_ONLY
checkpoint_schema   = ae.product_preparation_checkpoint.v1
replay_policy       = ae.product_preparation_resume.exact.v1
executor_kinds      = LOCAL_SKILL
installed_locks     = 2 (D04 and D12)
```

## Compatibility Invariants

1. Any checkpoint schema, replay-policy, executor-set, or Skill-lock drift
   changes the registration hash and fails registry admission.
2. Skill locks must exactly cover required capability bindings; missing,
   additional, malformed, or drifted locks fail closed.
3. Product resume checkpoints continue to reference the exact coordinator
   version and registration hash through the existing migration `2517` schema.
4. The shared runtime matcher and route source remain the only generalized
   wait/event transition mechanism.
5. WorkResult and NSL approval retain their existing typed validation and
   executable-step semantics.
6. No new database table, migration, queue, daemon, worker, or provider call is
   introduced.

## Verification

- focused coordinator and generalized resume compatibility regression:
  `134 passed`
- coordinator registration modules: statement `100%`, branch `100%`
- actual `nex_ae_test` persistence/restart smoke: `2 passed`
- PostgreSQL rollback residue: `0`
- AE Slice Gate: `6594 passed, 50 skipped`
- AE statement coverage: `96.41%` (threshold `95.00%`)
- AE branch coverage: `94.67%` (threshold `94.00%`)
- AE product ownership coverage: statement `97.06%`, branch `94.98%`
- contract validation: `PASS`
- golden-journey transition audit: `PASS`
- demo/product dependency audit: `PASS`
- AE coverage ownership: `PASS`, active graph `96`, conflicts `0`

Machine-readable Gate evidence:

```text
reports/quality/
mybee-w70-cp-m1-e2e-fx-01b6b1a4-ae-slice-gate.json
```

## Closure Decision

`CP-M1-E2E-FX-01B.6B.1A` is implementation-closed. The generalized
wait/event schema, typed Product bindings, runtime matching and routing, and
immutable coordinator registration are now mutually compatible.

The next Slice is `CP-M1-E2E-FX-01B.6B.2: Durable Preparation and Approval
Resume`. It may install the generic Product Coordinator handler and connect the
two owner-authoritative approval transitions, but it must retain the exact
registration above and may not introduce a Product-specific queue or worker.
