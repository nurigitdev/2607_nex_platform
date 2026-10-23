# P8-S67: Exactly-Once Golden A Retry Variants

## Objective

Prove that the admitted Golden A voucher-draft WRITE produces exactly one
authoritative EOS business mutation when delivery, worker, and publication
boundaries are retried.

## Boundary decision

- Reuse the P8-S65 approval lineage and P8-S66 canonical payload hash.
- Keep WC approval events and AE `RESUME_EXECUTION` jobs idempotent by their
  existing event ID, wait ID, and runtime-job dedup key.
- Treat a lost EOS response after a successful command as
  `UNKNOWN_COMMIT_STATE`; query EOS reconciliation before continuing.
- Re-entering the AE worker or result-publication path must reuse the same NSL
  idempotency evidence and EOS business operation.
- Do not add schema, migration, or public-contract fields.

## Implemented variants

1. Re-submit the exact approval event and preserve one matched inbox event.
2. Re-enqueue the exact `RESUME_EXECUTION` semantic job and preserve one job.
3. Discard the first successful EOS response after the actual commit, then
   reconcile the same `BusinessOperationId` to `COMMITTED`.
4. Re-enter the AE controlled-WRITE worker with a new invocation ID and require
   `REUSED`, `COMMITTED`, and `VERIFIED`.
5. Re-enter the worst-case publication recovery path and require the same
   idempotency reuse and verified voucher reference.

The protected gate counts EOS rows after all variants. Expected cardinality is
one business operation, one idempotency row, one voucher draft, two voucher
lines, and one outbox event. AE retains one idempotency record and three
append-only WRITE attempt records.

## Verification

- Focused P8-S53/S65/S66/S67 regression: `30 passed`, `4 skipped` protected
  tests.
- Actual AE/WC/OA/EOS PostgreSQL and live-provider protected gate: `PASS`,
  `16/16` checks.
- Fault injection observed `UNKNOWN_COMMIT_STATE`; EOS reconciliation returned
  `COMMITTED`.
- AE worker retry and publication recovery retry both returned
  `REUSED / COMMITTED / VERIFIED`.
- Final EOS cardinality: one business operation, one idempotency record, one
  voucher draft, two voucher lines, zero attachments, and one outbox event.
- Final AE cardinality: one idempotency record and three append-only WRITE
  attempt records.
- Tenant-scoped cleanup proved zero residue after the protected run.
- NeX-AE Slice Gate: `5,140 passed`, `37 skipped`; statement `98.41%`,
  branch `96.38%`.
- NeX-EOS Slice Gate: `384 passed`, `14 skipped`; statement `99.80%`,
  branch `100.00%`.
- Contract validation: 188 schemas, 250 positive examples, 217 negative
  examples, and 9 OpenAPI documents.
- Sanitized machine evidence is stored at
  `/tmp/nex-p8-s67-golden-a-exactly-once.json`; credentials, endpoints, raw
  prompts, model output, and private business payload are excluded.

## Exit Decision

P8-S67 is closed. All five duplicate/retry variants preserve the exact Golden
A lineage and one authoritative voucher-draft mutation. P8-S68 may package the
safe release, migration, identity, commit, verification, mutation, and residue
evidence without retaining protected business content.
