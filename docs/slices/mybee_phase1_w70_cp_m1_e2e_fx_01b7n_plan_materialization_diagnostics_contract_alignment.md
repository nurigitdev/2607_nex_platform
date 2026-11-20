# CP-M1-E2E-FX-01B.7N: READY_FOR_D04 Plan Materialization Diagnostics and Contract Alignment

## Status

- Date: `2026-11-20`
- Status: `IN PROGRESS`
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Predecessor: `CP-M1-E2E-FX-01B.7M`
- Database migration: none
- Public API change: none
- Remote provider: required for final exact-head replay only

## Failure Reconciliation

The `.7M` exact-head journey completed separate business and accounting Human
approvals, produced accounting evidence and posting admission, and advanced the
Product checkpoint to `READY_FOR_D04`. The following Product resume job then
failed as `M1_PLAN_MATERIALIZATION_INVALID`.

That single code collapses WorkIntent, checkpoint integrity, OA/EOS authority,
capability snapshot, Project lineage, context quality, timestamp, UUID, and
plan-validation failures. The persisted RuntimeJob therefore proves that plan
materialization failed but cannot identify the violated contract.

## Decision

1. Preserve `M1_PLAN_MATERIALIZATION_INVALID` as the compatibility error
   family.
2. Persist a bounded typed reason as the RuntimeJob `error_ref`.
3. Separate WorkIntent, READY checkpoint, integrity, authority, reference,
   capability, identity, Project, execution, conflict, degradation, timestamp,
   and validation failures.
4. Do not persist prompts, provider output, credentials, or unrestricted error
   text in RuntimeJob diagnostics.
5. Re-run the exact-head installed journey after diagnostic admission and fix
   only the contract proven by the typed failure.
6. Do not weaken OA authorization, EOS accounting SoD, capability admission,
   or immutable checkpoint hashes.
7. Reuse current RuntimeJob and Product preparation persistence; add no table
   or migration.

## Diagnosed Contract Drift

The exact-head diagnostic replay persisted `M1_PLAN_IDENTITY_MISMATCH`. A
bounded read of the same execution proved:

- AgentExecution principal: `employee-8101`;
- AgentExecution requester: `employee-8101`;
- READY checkpoint requester subject: `employee-8101`;
- canonical AgentContext identity field: `principal_id=employee-8101`.

The materializer alone read the non-canonical field `identity.subject_id`.
Canonical AgentContext admission has always required `tenant_id`,
`principal_id`, `agent_id`, and `agent_type`, so this was field-name drift, not
an authority mismatch. The materializer now compares `principal_id` to the
authoritative requester subject. It does not add a legacy `subject_id`
fallback, because accepting an unvalidated identity shape would weaken the
planning authority boundary.

## Exit Rule

The Slice closes only when focused regression and the AE Slice Gate pass, the
exact-head journey emits a typed materialization reason, the proven contract
misalignment is corrected without scenario fixtures, and the parent journey
advances beyond D04 plan materialization with zero residue.
