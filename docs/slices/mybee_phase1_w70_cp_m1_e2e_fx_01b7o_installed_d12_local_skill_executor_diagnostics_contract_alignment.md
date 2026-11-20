# CP-M1-E2E-FX-01B.7O: Installed D12 LOCAL_SKILL Executor Diagnostics and Contract Alignment

## Status

- Date: `2026-11-20`
- Status: `IN PROGRESS`
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

## Exit Rule

The Slice closes only when focused regression and the AE Slice Gate pass, an
exact-head installed replay persists the typed D12 failure, the proven contract
misalignment is corrected without scenario fixtures, the journey advances past
E1, and cleanup leaves zero runtime residue.
