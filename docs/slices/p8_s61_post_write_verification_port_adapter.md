# P8-S61: PostWriteVerificationPort Adapter

## Status

Completed on 2026-10-22.

## Scope

- Added an AE-owned HTTP adapter for the admitted NSL v0.2
  `PostWriteVerificationPort`.
- Bound post-WRITE verification to the authoritative EOS Voucher projection,
  `BusinessOperationId`, idempotency key, payload hash, and Voucher reference.
- Extended the existing EOS read-only verification projection with the
  operation and idempotency identities required for fail-closed lineage
  validation.
- Added actual admitted-wheel and `nex_eos_test` PostgreSQL evidence proving
  repeatable verification, SELECT-only behavior, row-count stability, and
  zero-residue cleanup.

No database table, migration, command retry, WRITE mutation, or remote model
provider was added.

## Source-Backed Contract Decision

The actual NSL v0.2 wheel exports `PostWriteVerificationPort` together with
its supporting `VerificationRequest` and `VerificationObservation` types.
The latter two symbols were therefore added to the Platform admission set;
the NSL source and wheel content were not changed.

The adapter accepts only the admitted `VerificationRequest` and
`WriteOutcomeIdentity` classes. Before issuing HTTP it validates the CREATE
tool, verification tool, strong read-after-write consistency hint, tenant,
invocation, BusinessOperation, provider transaction, Voucher reference,
idempotency, payload hash, and request hash.

## Verification Policy

| EOS observation | Port observation | Safety rule |
| --- | --- | --- |
| HTTP 200 with an exact committed Voucher projection and complete matching lineage | `matched=True` | Evidence binds the BusinessOperation and stable business-state hash. |
| Exact 404 `EOS_VOUCHER_VERIFICATION_NOT_FOUND` | `matched=False` | Only the authoritative EOS reason may prove absence. |
| Exact 409 `EOS_VOUCHER_VERIFICATION_BINDING_INVALID` | `matched=False` | Only the authoritative EOS reason may prove a binding mismatch. |
| Authentication denial, validation error, EOS 5xx, malformed projection, or lineage drift | typed adapter failure | The NSL verifier normalizes dependency ambiguity to `UNKNOWN`; CREATE is never retried. |
| Timeout or connection loss | timeout/connection failure | The NSL verifier preserves `COMMITTED` and reports verification `UNKNOWN`. |

Each attempt performs exactly one signed, no-cache HTTP GET. The timeout is
configured by `NEX_AE_EOS_VERIFICATION_TIMEOUT_SECONDS` and defaults to 15
seconds. Existing `NEX_EOS_BASE_URL` and
`NEX_AE_TO_EOS_SERVICE_TOKEN` settings are reused.

## Protected Evidence

The protected smoke loaded the admitted NSL v0.2 wheel ahead of repository
source, connected to the actual `nex_eos_test` database as `nex_eos_user`, and
created one Voucher through the real EOS command boundary. It then built an
actual NSL `VerificationRequest` from the committed WRITE identity and read it
twice through the adapter.

Both reads returned the same actual NSL `VerificationObservation` with
`matched=True`. SQLAlchemy statement capture proved that the verification
interval issued only SELECT statements. BusinessOperation, idempotency,
Voucher, Voucher-line, and outbox counts did not change, and business
authorization was invoked only for the original command. Cleanup removed all
tenant-scoped rows and verified zero residue.

## NSL Admission

- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- source-tree digest:
  `e7ffb07378ba01f4c9da6645f91b75614c605907`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- wheel size: `194308` bytes
- admitted public symbols: `30`
- release admission hash:
  `sha256:d4428b0714f6577cc3fb2fe92bf5231ad0bf15cf6879c3f08ee3cddc38e19622`
- adapter contract hash:
  `sha256:dc04bd9d3f9150b89eb9844a5ba974c20809ad86614485b1861be93409d213f1`

The protected P8-S06 compatibility smoke passed all eight checks while
preserving the host NSL v0.1 runtime and proving zero EOS mutation in the v0.2
controlled prefix.

## Verification

- P8-S61 unit suite: `66 passed`.
- P8-S61 adapter statement/branch coverage: `100% / 100%`.
- P8-S05 through P8-S61 focused regression: `380 passed`, `8 skipped`
  protected smokes.
- Actual admitted NSL v0.2 wheel plus `nex_eos_test` PostgreSQL smoke:
  `1 passed`.
- P8-S06 compatibility smoke: `PASS`, `8/8` checks.
- AE Slice Gate: `5,072 passed`, `32 skipped` protected smokes; statement
  coverage `98.40%`, branch coverage `96.36%`.
- EOS Slice Gate: `326 passed`, `12 skipped` protected smokes; statement
  coverage `99.80%`, branch coverage `100.00%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and formatting checks: passed.

## Exit Decision

P8-S61 is closed. AE can now verify a committed NSL WRITE against the
authoritative EOS read model without mutating business state or retrying the
CREATE command. Failed or unavailable verification remains distinct from
commit outcome, so P8-S62 can compose the controlled-WRITE runtime flow on a
stable post-write boundary.
