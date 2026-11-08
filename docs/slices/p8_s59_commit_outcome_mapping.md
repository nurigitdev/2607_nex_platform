# P8-S59: Commit Outcome Mapping

## Status

Completed on 2026-10-22.

## Scope

- Expanded the admitted NSL v0.2 public API with the actual commit-outcome
  types: `WriteOutcomeIdentity`, `WriteResultEnvelope`, `WriteCommitted`,
  `WriteNotCommitted`, and `WriteCommitUnknown`.
- Mapped the EOS canonical voucher result to one of those three terminal NSL
  outcomes without replacing NSL-issued operation, invocation, idempotency,
  approval, or payload-hash identity.
- Retained `execute_raw()` as the P8-S57 transport boundary and made
  `execute()` the admitted NSL `WriteExecutionPort` outcome boundary.
- Added actual admitted-wheel evidence for all three outcome classes and
  preserved the actual EOS PostgreSQL commit/replay smoke.

No database table, migration, public HTTP field, retry loop, or remote model
provider was added.

## Outcome Policy

| EOS observation | NSL outcome | Reason semantics |
| --- | --- | --- |
| Canonical 201 `CREATED` or 200 `REPLAYED` response | `WriteCommitted` | Exact committed identity, voucher reference, transaction reference, UTC commit time, and outbox evidence are required. |
| Canonical 4xx response | `WriteNotCommitted` | EOS explicitly rejected the command. A bounded EOS reason code is retained when its status lineage is valid. |
| 5xx response | `WriteCommitUnknown` | The command may have crossed the provider boundary; reconciliation is required. |
| Timeout or connection loss | `WriteCommitUnknown` | No automatic retry is permitted because commit state is unknown. |
| Malformed or contradictory success response | `WriteCommitUnknown` | An untrustworthy acknowledgement cannot prove either commit or non-commit. |
| Local failure before dispatch | `WriteNotCommitted` | The command is known not to have reached EOS. |

Each invocation sends at most one EOS command. `WriteCommitUnknown` is not
converted into a generic retry and does not manufacture a committed result.

## Result Contract

The runtime binding supplies the expected NSL result type and data
classification. The adapter does not import private NSL implementation modules
or invent type metadata. It obtains the admitted `ValueEnvelope` factory from
the canonical request envelopes and builds this committed value:

```text
value              = {"voucher_no": <EOS voucher id>}
business_reference = eos.voucher_draft:<EOS voucher id>
provider_tx_id     = <NSL/EOS BusinessOperationId>
evidence_refs      = EOS BusinessOperation + outbox event
```

Missing result metadata, an unavailable envelope factory, a non-UTC commit
time, invalid entity references, extra result fields, or mismatched lineage
fails closed.

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

Reproducible admission and isolated v0.2 readiness both passed.

## Protected Evidence

The actual admitted-wheel smoke created a real NSL `WriteCallRequest`, mapped
201, 403, and 503 responses, and asserted real `WriteCommitted`,
`WriteNotCommitted`, and `WriteCommitUnknown` instances. The committed result
retained the `VoucherDraft` type and `CONFIDENTIAL` classification.

The existing protected EOS smoke connected as `nex_eos_user` to
`nex_eos_test`, verified the migration baseline, executed create and exact
replay through the EOS FastAPI route, checked the durable voucher, lines,
BusinessOperation, idempotency, and outbox rows, then removed all tenant rows.
The P8-S57 smoke now calls the explicit raw transport API so its original
contract remains unambiguous after the P8-S59 outcome activation.

## Verification

- Outcome mapper unit suite: `60 passed`.
- Outcome mapper statement/branch coverage: `97%` combined.
- Actual admitted NSL v0.2 outcome smoke: `1 passed`.
- Actual `nex_eos_test` PostgreSQL commit/replay/zero-residue smoke: `1 passed`.
- AE Slice Gate: `4,962 passed`, `30 skipped` protected smokes.
- AE Slice Gate statement coverage: `98.37%`.
- AE Slice Gate branch coverage: `96.32%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and `git diff --check`: passed.

## Exit Decision

P8-S59 is closed. The AE-to-EOS execution boundary now returns the admitted
NSL commit-outcome algebra, preserves committed evidence and lineage, and
routes every ambiguous provider observation to explicit reconciliation rather
than an unsafe retry or inferred success.
