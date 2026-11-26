# W80-CA00G.6B Accounting Correction Re-entry and Latest-Revision Resume Closure

## Status

CLOSED / PROTECTED POSTGRESQL ACCEPTED / AE SLICE GATE PASSED

## Product Boundary

Business approval rejection remains terminal. Accounting approval rejection is
correctable: EOS returns the authoritative VoucherCandidate to
`RETURNED_FOR_CORRECTION`, and AE appends a new Product preparation checkpoint
in `WAITING_VOUCHER_REVIEW` instead of mutating or reopening the old checkpoint.

The implementation reuses the generalized wait/event persistence and existing
RuntimeJob queue. It adds no table or queue. Migration
`2519_ae_product_wait_active_authority.sql` narrows the existing Product wait
uniqueness rule to one `PENDING` authority per execution and reference so an
immutable historical wait can coexist with its correction wait.

## Correction Contract

1. A business approval `REJECTED` event creates the existing terminal
   `PREPARATION_CANCELLED` checkpoint and cannot be resubmitted in place.
2. An accounting approval `REJECTED` event is accepted only while the latest
   Product checkpoint is `WAITING_ACCOUNTING_APPROVAL`.
3. EOS must report `RETURNED_FOR_CORRECTION` and an immutable `RETURN` event
   bound to the current Candidate revision and the rejected accounting case.
4. AE appends a new `WAITING_VOUCHER_REVIEW` checkpoint and wait. The rejected
   accounting wait, event, checkpoint, and RuntimeJob lineage remain immutable.
5. Explicit requester resubmission is admitted only from the current Candidate
   revision. A historical `SUBMIT`, `RETURN`, case, or revision cannot advance
   the runtime.
6. Accounting approval and posting admission use the latest current-revision
   `SUBMIT`, not the first historical submit event.
7. Authority lookup selects only a `PENDING` wait. Exact ACK-loss replay first
   resolves the deterministic persisted event ID, so it does not reopen or
   ambiguously select a historical wait.

## History and Archive Policy

- `correction_history_mode`: `APPEND_ONLY_AUDIT`
- `correction_active_selection`: `LATEST_CHECKPOINT_ONLY`
- `accounting_correction_cycle`: monotonic integer `0..N`; no arbitrary product
  cap is introduced in this Slice.
- `correction_archive_policy`: `TERMINAL_POLICY_CONTROLLED`

The active runtime reads only the latest checkpoint in the coordinator lineage,
so old correction checkpoints do not accumulate in the execution path. Physical
archive, compaction, or deletion is outside this Slice and may occur only under a
future retention policy after the lineage is terminal. Historical rows are never
reused as active authority.

## Safety and Verification

- Fresh OA/EOS authority resolution remains required at every resume.
- Owner, tenant, authority kind, accounting case, Candidate revision, and event
  identity are fail-closed.
- Existing accounting separation of duties remains authoritative; correction
  re-entry does not allow the preparer to approve the voucher.
- Restart and exact replay converge on one latest checkpoint and one active wait.
- Actual isolated-schema `nex_ae_test` smoke covers migration, correction,
  restart, replay, ACK loss, cross-tenant rejection, latest pending wait
  selection, final approval, and zero-residue schema cleanup.
- Remote model providers are not required for this corrective Slice.

Recorded evidence:

- Focused regression: `123 passed, 2 skipped`; exact replay drift matrix:
  `9 passed`.
- Actual PostgreSQL protected smoke: `2 passed in 17.24s`.
- AE Slice Gate: `7154 passed, 57 skipped`, `6/6 PASS`.
- Statement coverage: `96.42%` (threshold `95.00%`).
- Branch coverage: `94.61%` (threshold `94.00%`, previous value retained).
- Contract validation: `pass` across `280` schemas, `322` examples,
  `260` negative examples, and `10` OpenAPI documents.

## Installed Admission

- Transaction preparation adapter: `1.2.0`.
- Product coordinator: `1.3.0`, registry version `5`.
- Canonical Product coordinator activation and rollback locks: version `6`.
- Historical lock versions remain packaged for replay and rollback evidence.

The parent resume point is `W80-CA00G.7`.
