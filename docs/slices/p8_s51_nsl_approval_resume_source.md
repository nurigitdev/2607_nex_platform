# P8-S51: NSLApprovalResumeSource

## Status

Completed on 2026-10-22.

## Scope

- Added a typed sibling of the P7 WorkResult resume source for NSL approval.
- Resolves authority only from an exact running `RESUME_EXECUTION` claim and
  its current worker lease identity.
- Reads the existing RuntimeJob, wait, executable step, event inbox,
  ApprovalRequest, and immutable ApprovalEvidence sources of record.
- Returns bounded lineage and the validated typed event; it does not expose
  the protected ApprovalRequest body or construct an NSL token yet.

## Fail-Closed Rules

Resolution requires all of the following to match:

- current RuntimeJob and running attempt tenant, job, worker, and lease;
- exact job/wait/parent execution/executable step identity;
- `LOCAL_SKILL` and `WAITING` executable step;
- `NSL_APPROVAL` and `RESUME_QUEUED` wait;
- exact matched event and `resume_runtime_job_id`;
- exact approval request, work-item, evidence, NSL execution, business
  operation, integrity, and resume-token references;
- canonical approval resume contract and positive checkpoint version;
- `MATCHED` typed event whose decision equals immutable evidence.

Malformed persisted JSON, missing joined authority, stale claims, and any
lineage drift fail closed with typed adapter errors.

## Persistence

No migration was added. P8-S51 is a read adapter over existing P5/P6/P8
sources of record.

## Verification

- Focused tests: `25 passed`.
- Focused module coverage: statement `100%`, branch `100%`.
- AE Slice Gate: `4,778 passed`, `23 skipped`.
- AE Slice Gate coverage: statement `98.36%`, branch `96.26%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and diff checks passed.

## PostgreSQL Boundary

This Slice adds no schema and does not independently assemble a partial P5/P6
execution graph in PostgreSQL. The actual PostgreSQL `LOCAL_SKILL` approval
resume journey, including this source and its UUID/text normalization, is the
explicit P8-S53 protected gate. P8-S50 already proved migration 2505 and typed
event persistence against `nex_ae_test`.

## Exit Decision

P8-S51 is closed. P8-S52 may consume only this exact durable authority when it
constructs the admitted NSL v0.2 `ResumeToken` and invokes
`ApprovalResumeCoordinator`.
