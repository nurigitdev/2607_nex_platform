# P8-S60: Reconciliation Adapter

## Status

Completed on 2026-10-22.

## Scope

- Added an AE-owned, read-only EOS reconciliation adapter for an admitted NSL
  `WriteCallRequest` whose prior result is `WriteCommitUnknown`.
- Queried the canonical EOS BusinessOperation projection by
  `BusinessOperationId` and mapped only authoritative EOS state to the actual
  admitted NSL v0.2 write-outcome classes.
- Preserved `RECONCILIATION_REQUIRED` for absent, unavailable, malformed,
  contradictory, or still-pending observations.
- Added actual admitted-wheel and `nex_eos_test` PostgreSQL evidence proving
  commit-after-ack-loss reconciliation, repeated read stability, durable
  evidence, and zero-residue cleanup.

No database table, migration, public HTTP field, command retry, or remote model
provider was added.

## Source-Backed Boundary Decision

The admitted NSL v0.2 public API has the write request and three-way outcome
algebra but no public `ReconciliationPort` type. P8-S60 therefore keeps the
reconciliation transport in AE and returns existing admitted NSL result
classes. It does not invent an NSL symbol or import a private NSL module.

The adapter accepts both the original request and its unknown result. Before
any network call it verifies their operation, invocation, idempotency,
approval, payload-hash, and business-operation identity. A result from another
write cannot be used to query or classify the request.

## Reconciliation Policy

| EOS observation | NSL outcome | Safety rule |
| --- | --- | --- |
| `COMMITTED` with `COMMITTED_CONFIRMED` and complete matching lineage | `WriteCommitted` | Voucher and transaction references plus UTC observation time are required. |
| `NOT_COMMITTED` with `NOT_COMMITTED_CONFIRMED` and complete matching lineage | `WriteNotCommitted` | Only the authoritative EOS projection may prove non-commit. |
| `PENDING` with `RECONCILIATION_REQUIRED` | `WriteCommitUnknown` | The reason remains `RECONCILIATION_REQUIRED`. |
| 404, authentication denial, or EOS 5xx | `WriteCommitUnknown` | Absence or service failure never proves non-commit. |
| Timeout, network loss, malformed projection, or lineage drift | `WriteCommitUnknown` | Ambiguity remains explicit and fail-closed. |

Every unresolved outcome keeps `reason_code=RECONCILIATION_REQUIRED`; the
specific transport, HTTP, or validation cause is retained separately in its
evidence references for diagnostics.

Each reconciliation attempt performs exactly one no-cache HTTP GET and never
issues an EOS command or an automatic retry. The dedicated timeout is
configured with `NEX_AE_EOS_RECONCILIATION_TIMEOUT_SECONDS` and defaults to 15
seconds. Existing `NEX_EOS_BASE_URL` and
`NEX_AE_TO_EOS_SERVICE_TOKEN` settings are reused.

## Protected Evidence

The protected test loaded the admitted NSL v0.2 wheel ahead of the source
tree, connected to the actual `nex_eos_test` database as `nex_eos_user`, and
committed one voucher through the EOS command API. It then treated the command
acknowledgement as lost and reconciled the resulting unknown outcome twice
through the EOS BusinessOperation GET route.

Both reads returned an actual NSL `WriteCommitted`. PostgreSQL retained exactly
one BusinessOperation, idempotency record, voucher, outbox event, and the two
expected voucher lines. Fresh business authorization was invoked only by the
original command, not by reconciliation. The test removed all tenant-scoped
rows and verified zero residue.

## NSL Admission

The source and wheel content remain unchanged:

- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- source-tree digest:
  `e7ffb07378ba01f4c9da6645f91b75614c605907`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- wheel size: `194308` bytes
- admitted public symbols: `28`
- release admission hash:
  `sha256:3032fcfd71d0f123d9ebf21e3c9ab054624b4575b680d7dadddad714be982f5b`
- adapter contract hash:
  `sha256:7c56c76aed399a12db36a9a13440ceb5240ef4875b1ab99fd640dfba01d921bd`

## Verification

- P8-S60 unit suite: `44 passed`.
- Reconciliation module statement/branch coverage: `100% / 100%`.
- P8-S57 through P8-S60 focused regression: `117 passed`, `6 skipped`
  protected smokes.
- Actual admitted NSL v0.2 wheel plus `nex_eos_test` PostgreSQL smoke:
  `1 passed`.
- AE Slice Gate: `5,006 passed`, `31 skipped` protected smokes.
- AE Slice Gate statement coverage: `98.38%`.
- AE Slice Gate branch coverage: `96.34%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and `git diff --check`: passed.

## Exit Decision

P8-S60 is closed. AE can now reconcile an ambiguous NSL write through the
authoritative EOS read model without re-executing the command or inferring a
terminal state from transport behavior. P8-S61 can build its verification and
runtime orchestration on this stable three-way reconciliation boundary.
