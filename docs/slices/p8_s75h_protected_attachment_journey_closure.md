# P8-S75H: Protected Attachment Journey And P8.7A Closure

## Status

Completed on 2026-10-23. P8.7A is closed and ready to hand off an
attachment-bearing Voucher to P8.8 reliability and reconciliation work.

## Protected Journey

The opt-in protected journey used the actual `nex_ae_test`, `nex_wc_test`,
`nex_oa_test`, and `nex_eos_test` PostgreSQL databases together with a
digest-pinned RustFS `1.0.1` container and SSE-S3 encryption. It performed the
following sequence without a remote model provider:

1. authenticated owner upload of image, PDF, and opaque ZIP evidence;
2. exact duplicate upload replay with one immutable object identity;
3. reconstruction of the AE repository and object gateway from PostgreSQL and
   RustFS state;
4. partial-batch rejection, finalization, immutable manifest lock, and lock
   replay;
5. owner-scoped preview plus post-lock upload/removal rejection;
6. OA-authorized WC approval and EOS Voucher commit;
7. idempotent EOS command replay and exact three-attachment verification;
8. manifest-hash tamper rejection and privacy-preserving cross-tenant object
   reference rejection;
9. deletion of all journey rows and object versions followed by zero-residue
   checks.

Result: `1 passed`, `0 skipped`. All four databases reported zero rows for the
test tenant after cleanup, and no test object remained in RustFS.

Protected execution is enabled only by
`NEX_P8_S75H_PROTECTED_SMOKE=1` together with the four service-owned test
database URLs and owner-scoped RustFS endpoint/credential environment
variables. The Repository Full Gate intentionally leaves this test skipped so
an ordinary regression run cannot contact protected infrastructure.

## Contract Closure

All seven public Voucher attachment operations are now described in the AE
OpenAPI document, including authenticated owner scope, multipart upload,
idempotent replay, immutable lock, private content delivery, and explicit
error boundaries. This restored the historical S101 audit to its admitted
baseline of 33 classified legacy gaps instead of counting the seven new P8.7A
routes as undocumented drift.

S146 historical object-storage acceptance now validates configuration and
artifact digests against the Git blobs at its recorded accepted source
revision. Current, intentionally extended object-storage code can therefore
evolve without invalidating immutable S146 evidence, while missing revisions
or files still fail closed.

Contract validation result:

- schemas: `191`;
- positive examples: `253`;
- negative examples: `221`;
- OpenAPI documents: `9`.

## Repository Full Gate

The complete Repository Full Gate exited successfully after executing the
full pytest, coverage, contract, browser, deterministic flow, audit, and
closure runner sequence.

- pytest: `17,110 passed`, `98 skipped`;
- statement coverage: `96.76%` against the `95.00%` threshold;
- branch coverage: `96.14%` against the `85.00%` threshold;
- pytest duration: `33m 12s`;
- contract validation: PASS;
- Full Gate process exit: `0`.

The skips are explicit protected/live opt-ins. P8-S75H itself has separate
zero-skip protected evidence as recorded above.

## Exit Decision

P8.7A is closed. The approved Voucher is bound to an immutable, owner-private
attachment manifest; EOS stores and verifies exact attachment metadata but
does not receive RustFS credentials; retry and restart preserve one Voucher;
and tamper, post-lock mutation, partial batch, and cross-tenant substitution
fail closed.

P8.8 may now use this attachment-bearing journey as a concrete input for
reconciliation, recovery, and reliability acceptance.
