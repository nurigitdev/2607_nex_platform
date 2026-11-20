# CP-M1-E2E-FX-01B.7P: Installed D04 Controlled-Skill Initial Diagnostics and Contract Alignment

## Status

- Date: `2026-11-20`
- Status: `IN PROGRESS`
- Parent boundary: `CP-M1-E2E-FX-01B.7`
- Predecessor: `CP-M1-E2E-FX-01B.7O`
- Database migration: none
- Public API change: none
- Remote provider: required only for final exact-head replay

## Failure Reconciliation

The `.7O` exact-head replay completed D12 through the installed NSL v0.2
runtime and reached `READY_FOR_D04`. The D04 `CONTINUE_EXECUTION` RuntimeJob
then failed with `ae.product_controlled_skill_initial_failed`. That generic
error hides whether authority resolution, artifact admission, durable binding,
NSL execution construction, approval publication, or wait registration failed.

Source reconciliation also found a direct conflict with the `.7M` accounting
separation-of-duties decision. The D04 initial path requires the requester to
hold `finance:journal:approve`, although the admitted acceptance contract grants
the requester `finance:journal:request-approval` and reserves approval authority
for a distinct accounting approver.

The first exact-head replay after that authority correction exposed a second,
independent contract defect. The signed D04 Skill `1.0.0` had no `check`
statement. NSL v0.2 therefore completed its controlled prefix with validation
status `NO_CHECK`; the runtime correctly refused to publish an approval request
and persisted `ae.product_controlled_skill_approval_not_suspended`. This was a
Skill contract mismatch, not an approval-authority or publication failure.

## Decision

1. Preserve bounded stage-specific D04 initial failure codes across the P5
   executor boundary. Never persist provider bodies, unrestricted exception
   text, credentials, or prompt content.
2. Require the originating requester to have current
   `finance:journal:request-approval` authority when entering the D04 approval
   wait.
3. Preserve requester and approver as distinct principals. Self-approval is
   fail-closed.
4. On controlled-WRITE resume, revalidate both principals:
   - requester: current request-approval authority;
   - evidence-bound approver: current `finance:journal:approve` authority.
5. Keep the governed operation actor bound to the requester while including the
   evidence-bound accounting approver in typed authorization facts. The
   approval evidence remains the authority for the decision; role alone does
   not grant write authority.
6. Admit the existing runtime target role `finance_approver` for the accounting
   approver in installed acceptance in addition to the EOS leadership position
   `GROUP_LEAD`.
7. Reuse the existing Platform ApprovalEvidence, generalized wait/event,
   RuntimeJob, NSL binding, OA, WC, and EOS structures. Add no migration,
   scenario fixture, fixed identity, or tenant-specific fallback.
8. Do not weaken the NSL runtime to accept `NO_CHECK`. Publish D04 Skill
   `1.0.1` with deterministic checks for the admitted Journal command schema and
   positive VoucherCandidate version/revision before its approval statement.
9. Promote the corrected Skill through a new signed NSP, verification-only
   public key, Product Capability Registry, runtime admission, runtime
   activation, and Product coordinator activation. Preserve every v1 artifact
   unchanged as controlled rollback evidence.
10. Keep Skill and Tool contract versions independent. D04 Skill `1.0.1`
    continues to require the admitted Journal Tool contract `1.0.0`; the
    runtime resolves that version from the signed NSO `required_tools` record
    and fails closed unless exactly one matching WRITE Tool is present.

## Implemented Boundary

- D04 `1.0.1` semantic hash:
  `sha256:25fc90a2a81499d646ab6df5bb9b2c9727343a577a1341ecf97563ac5c6519c9`.
- Signed release: `nex-mybee-m1-d04-d12-checkpoint-v2`; private signing key was
  not persisted, and only the Ed25519 verification key is packaged.
- Active immutable bindings:
  - Product Capability Registry `v3`, registry version `5`;
  - runtime admission `v3`;
  - runtime activation `v3`;
  - Product coordinator activation/rollback `v2`.
- Rollback remains bound to signed release v1, registry v2, and runtime
  admission v2. Active OCI contexts package both current and rollback artifacts.
- The source-level controlled-prefix test executes the actual signed D04 Skill,
  proves `ALL_PASS`, and requires both checkpoint and approval request output.
- Installed authority composition no longer substitutes the Skill version for
  the Tool contract version; the distinct `1.0.1`/`1.0.0` pair is covered by a
  fail-closed regression test.

## Verification In Progress

- Focused Product runtime, coordinator, planning, deployment, and historical
  compatibility regression: `451 passed, 1 skipped`.
- Active/rollback binding and Skill/Tool version reconciliation regression:
  `284 passed`.
- Product runtime deployment audit: `PASS`; no business fixture is used by the
  active runtime.
- AE Slice Gate: `PASS`; `6,896 passed, 53 skipped`, statement coverage
  `96.46%`, branch coverage `94.71%`, and all six contract/audit commands
  completed.
- Remaining exit work: exact-head OCI rebuild, DGX preflight, installed
  protected replay, and eight-database/Compose zero-residue check.

## Exit Rule

The Slice closes only when focused regression and the AE Slice Gate pass, an
exact-head installed replay enters the D04 NSL approval wait with separate
requester and accounting approver authority, and any later failure is preserved
as a distinct downstream typed boundary. All Compose and isolated PostgreSQL
state must be removed after the protected run.
