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

## Exit Rule

The Slice closes only when focused regression and the AE Slice Gate pass, an
exact-head installed replay enters the D04 NSL approval wait with separate
requester and accounting approver authority, and any later failure is preserved
as a distinct downstream typed boundary. All Compose and isolated PostgreSQL
state must be removed after the protected run.
