# CP-M1-E2E-FX-01B.6B.5A.4 Activation Lock, Compose, OCI, and Readiness

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_Installed_Product_Coordinator_Authority_and_Dispatch_Closure_v1.0.md`
- Database migration: none
- Remote provider: not required; live Product acceptance remains in `.5A.5`
- Next Slice: `CP-M1-E2E-FX-01B.6B.5A.5`

## Activation Boundary

The installed AE API and Agent Runtime Worker now admit the Product
Coordinator through a dedicated immutable activation lock. The existing D04
and D12 Skill activation lock remains unchanged and continues to own Skill
artifacts. The new lock binds only the Product coordination layer:

- Product Coordinator registry and registration hashes;
- Product Capability Registry and planning-policy hashes;
- EOS/OA authority resolver and transaction-preparation identities;
- D04/D12 installed Skill bundle locks;
- generic `EXECUTABLE_STEP` and `PRODUCT_COORDINATOR` handlers;
- Product preparation checkpoint schema;
- the complete AE migration inventory and current head;
- installed API and Agent Runtime Worker process identities; and
- a hash-bound rollback receipt.

The committed activation hash is
`sha256:2a1f8a3c4e9a2a6bf023fc30753fdb724c63a94246e5d0ba24c6ae59fb8545ad`.
The rollback receipt hash is
`sha256:ca62f44052e7873a11b3d5cb98676dcf87172f8c28553b582e430eae169bbc06`.
The admitted migration head is `2517_ae_product_preparation_resume`.

## Installed Composition

- staging and production API/worker processes activate the coordinator only
  when `NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH` is explicitly configured;
- profiles without the activation path remain `CONTRACT_ONLY`, preserving
  existing development and test composition behavior;
- the Agent Runtime Worker shares one installed Product Skill runtime between
  executor-profile and Product Coordinator composition;
- canonical Compose supplies both activation and rollback lock paths to the
  AE API and worker;
- the canonical AE runtime OCI context packages both immutable lock files;
- startup fails closed on lock drift, rollback drift, migration drift,
  unavailable transaction preparation, or missing authority configuration.

The deployment documents contain identities and hashes only. Tenant, company,
Project, amount, currency, account, ratio, approval-policy, secret, and other
business values are rejected from activation and readiness documents.

## Rollback and Readiness

Rollback changes the Product Coordinator to `CONTRACT_ONLY` while preserving
existing checkpoint, generalized wait/event, RuntimeJob, AgentPlan, and
ExecutablePlan history. It does not delete or rewrite Product lineage.

The readiness projection reports the exact activation, rollback, registry,
registration, capability, migration, planning-policy, and handler identities.
It does not expose business content or service credentials.

## Verification

- focused activation and adjacent composition regression: `94 passed`
- canonical AE Slice Gate: `PASS`
  - commands: `6/6`
  - selected test files: `459`
  - duration: `577.093 seconds`
  - statement coverage: `96.3792%`
  - branch coverage: `94.6284%`
- active Product coverage:
  - statement: `97.0045%`
  - branch: `94.9253%`
- Golden Journey transition, demo/product dependency, coverage ownership,
  lint, compile, and diff checks: PASS
- no new migration, queue, worker, executor kind, or public API field
- evidence:
  - `reports/quality/mybee-w70-cp-m1-01b6b5a4-ae-slice-gate.json`
  - `reports/coverage/mybee-w70-cp-m1-01b6b5a4-ae-slice-gate.report_ae_coverage_ownership.json`
  - `reports/quality/slice-latest.json`

## Closure

`CP-M1-E2E-FX-01B.6B.5A.4` is closed. Product Coordinator activation is now
an immutable, fail-closed installed-runtime decision for both AE processes,
with an explicit history-preserving rollback boundary and no scenario fixture
or business default embedded in deployment configuration.
