# P8-S50: Typed AE Approval Event Inbox

## Status

Completed on 2026-10-22.

## Scope

- Extended the existing `ae_external_event_inbox` instead of creating a
  second event inbox.
- Added the bounded `NSL_APPROVAL_DECIDED` event shape with approval request,
  work-item, evidence, NSL execution, and business-operation references.
- Kept approval events reference-only: no protected request body, approval
  evidence body, or fabricated WorkResult is stored in the inbox.
- Added idempotent event intake and reconciliation for event-first and
  evidence-first delivery orders.
- Added exact approval evidence and wait-lineage validation before a
  `RESUME_EXECUTION` job can be scheduled.
- Reused the canonical approval resume contract from the S47 publication
  boundary and normalized PostgreSQL UUID values at the service boundary.

## Runtime Semantics

- A matching pending `NSL_APPROVAL` wait can enqueue one deterministic resume
  job only when its parent execution is `WAITING_APPROVAL`, its step is
  `WAITING`, and its executor is `LOCAL_SKILL`.
- Lineage or contract drift rejects the inbox event without changing the
  pending wait.
- A terminal parent, step, or cancelled wait rejects the event and cancels a
  still-pending wait.
- Missing evidence or a not-yet-ready execution shape keeps the event in
  `RECEIVED` for later reconciliation.

## Persistence

- Added migration `2505_ae_nsl_approval_event_inbox`.
- `result_id` is nullable only for the typed approval event shape.
- A database check constraint keeps WorkResult and approval event columns
  mutually exclusive and validates bounded approval references.
- Added a partial approval-event lookup index; no new table was introduced.

## Verification

- Focused unit tests: `23 passed`.
- Focused module coverage: statement `99.52%`, branch `98.28%`.
- Actual `nex_ae_test` migration and protected PostgreSQL smoke: `1 passed`.
  The smoke directly verified the typed row, `result_id IS NULL`, pending wait,
  and absence of a fabricated resume job for a non-`LOCAL_SKILL` P4 step.
- AE Slice Gate: `4,753 passed`, `23 skipped`.
- AE Slice Gate coverage: statement `98.35%`, branch `96.25%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and diff checks passed.

## Exit Decision

P8-S50 is closed. AE now has a durable typed approval event intake and
reconciliation boundary. P8-S51 will resolve and validate the exact running
resume job. The complete PostgreSQL `LOCAL_SKILL` wait-to-resume journey is
reserved for P8-S53, where proper P5/P6 execution lineage is available.
