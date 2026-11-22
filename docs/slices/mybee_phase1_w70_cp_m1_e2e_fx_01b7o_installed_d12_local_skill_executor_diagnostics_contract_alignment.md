# CP-M1-E2E-FX-01B.7O: Installed D12 LOCAL_SKILL Executor Diagnostics and Contract Alignment

## Status

- Date: `2026-11-20`
- Status: `CLOSED / DOWNSTREAM D04 BLOCKER OPEN`
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Predecessor: `CP-M1-E2E-FX-01B.7N`
- Database migration: none
- Public API change: none
- Remote provider: required for final exact-head replay only

## Failure Reconciliation

The `.7N` exact-head replay crossed `READY_FOR_D04` plan materialization and
persisted two executable plans. Executable step `E1` then failed while running
the admitted D12 `PROJECT.WORK_CODE_SET.GET` Skill through `LOCAL_SKILL`.

The EOS D12 adapter already exposes bounded `error_code`, `retryable`, and
`status_code` fields, but the NSL runtime converted an adapter exception into a
generic runtime failure. The outer P5 worker consequently persisted only
`ae.p5_executor_callback_failed`, hiding the violated provider contract.

## Decision

1. Preserve typed Tool adapter failures across the installed NSL execution
   boundary without exposing provider response bodies or unrestricted exception
   text.
2. Map a bounded adapter `error_code` and `retryable` flag into the existing
   `P5StepExecutorError` and RuntimeJob settlement path.
3. Map an untyped handler exception to the provider-neutral
   `ae.nsl_tool_handler_failed` code.
4. Keep NSL Skill identity, Product Capability Registry, EOS API, OA authority,
   and executable-plan contracts unchanged until an exact-head replay identifies
   the actual D12 mismatch.
5. Correct only the mismatch proven by the typed live evidence. Do not add M1,
   tenant, Project, or fixture-specific fallback behavior.
6. Reuse existing RuntimeJob, StepResult, NSL binding, and EOS Project WorkCode
   persistence. Add no table or migration.

## As-Built Contract Alignment

The exact-head investigation exposed and corrected six independent boundary
defects without changing the admitted D12 Skill, Product Capability Registry,
EOS API, or database schema.

1. Installed Tool handler errors now preserve only a bounded typed error code
   and retryability flag through the shared NSL adapter. Unknown exceptions use
   `ae.nsl_tool_handler_failed`.
2. D12 artifact resolution, request binding, and invocation binding have
   distinct bounded failure codes instead of collapsing into one callback
   error.
3. Persisted executable-step projections retain `required_capability` and
   `capability_version`, so the worker dispatches the admitted capability after
   a database round trip.
4. The protected acceptance requester has the existing
   `project:work-code:read` scope required by EOS. No acceptance-only bypass was
   added.
5. `EXECUTABLE_PLAN` is an admitted input-provenance value for requests built
   from a persisted executable plan.
6. The EOS Project WorkCode adapter returns a fresh JSON-compatible `dict` at
   the NSL Tool boundary. The previous `MappingProxyType` result was immutable
   but was rejected by the installed NSL v0.2 `MockToolExecutor` as `NSL-E8002`.
   Immutability remains inside registry and runtime configuration boundaries;
   Tool results remain serialization-safe values.

Relevant exact-head commits are:

- `9a03619f` typed installed D12 executor failures
- `794edec2` installed D12 READ-stage diagnostics
- `a4610fa7` local Skill boundary diagnostics
- `a0abaa9b` persisted step capability identity
- `8fc025d0` D12 acceptance authority alignment
- `2484899f` executable-plan input provenance admission
- `5207c3bf` NSL-compatible D12 Tool result projection

## Verification

- Focused installed D12 adapter/runtime regression: `42 passed`.
- P6 NSL binding/backend, step executor, multi-step projection, M1 catalog,
  installed runtime, and product golden regression: `205 passed`.
- Canonical exact-head image evidence at `5207c3bfd142`:
  - report: `reports/deployment/mybee-w70-cp-m1-01b7o-final-canonical-images.json`;
  - `9/9` OCI images and manifests built;
  - `9/9` non-root runtime users;
  - `12/12` packaged background process checks;
  - complete release set, with no registry push.
- AE product runtime image admission passed with NSL `0.2.1`, the admitted D12
  and D04 capabilities, and no historical Golden A dependency.
  Evidence: `reports/deployment/mybee-w70-cp-m1-01b7o-final-ae-product-runtime-image.json`.
- DGX protected preflight passed `3/3` for generation, embedding, and reranking.
- The first protected run stopped at a transient OpenBao initialization
  transport failure after all `210` migrations; its eight isolated schemas were
  removed with `zero_residue=true`.
- The second protected run used actual OA, AG, AE, CX, MO, WC, EOS, and WA dev
  PostgreSQL databases, OpenBao, RustFS, Playwright, and the live generation
  provider. It created both separated approval stages and persisted D12 as:
  - backend profile: `NSL_V02_IN_PROCESS`;
  - state: `SUCCEEDED`;
  - terminal timestamp: present.
- The journey then advanced to `READY_FOR_D04`. The subsequent D04
  `CONTINUE_EXECUTION` failed with
  `ae.product_controlled_skill_initial_failed`; this is downstream of the D12
  boundary and is not hidden as a 7O success condition.
- The interrupted installed stack was explicitly stopped. All Compose
  containers, networks, and volumes were removed, and all eight isolated
  `m1_01b7_*` schemas were dropped.
- AE Slice Gate:
  - report: `reports/quality/cp-m1-e2e-fx-01b7o-ae-slice-gate.json`;
  - `6892 passed`, `53 skipped` protected opt-in tests;
  - statement coverage `96.45%` against `95.00%`;
  - branch coverage `94.72%` against `94.00%`;
  - contract validation `PASS` for `274` schemas, `320` examples,
    `260` negative examples, and `10` OpenAPI documents;
  - AE coverage ownership and tiered Slice Gate: `PASS`.

No provider secret, database password, prompt content, or unrestricted provider
response is included in committed evidence.

## Downstream Handoff

The recommended next corrective boundary is a separate installed D04
controlled-Skill initial diagnostics and contract-alignment Slice. It should
first preserve the bounded root error behind
`ae.product_controlled_skill_initial_failed`, then correct only the proven
generic product-runtime mismatch. It must not introduce tenant, Project, M1, or
fixture-specific fallback behavior.

## Exit Rule

The Slice closes because focused regression and the AE Slice Gate pass, the
exact-head installed replay proved and corrected the D12 contract mismatch
without scenario fixtures, E1 completed through the installed NSL runtime, and
cleanup left zero runtime residue. The downstream D04 blocker remains explicitly
open and prevents the parent `.01B.7` journey from closing.
