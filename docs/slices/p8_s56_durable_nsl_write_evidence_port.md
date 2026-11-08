# P8-S56: Durable NSL WriteEvidencePort

## Status

Completed on 2026-10-22.

## Scope

- Added the AE-owned `ae_nsl_write_evidence` PostgreSQL source of record.
- Added `SqlAlchemyNslWriteEvidencePort` over the admitted NSL v0.2
  `WriteEvidencePort` contract.
- Admitted `WriteEvidencePort`, `WriteAttemptRecord`, and
  `WriteRequestedReceipt` through the existing NSL v0.2 wheel boundary.
- Preserved the NSL ordering that durable `WRITE_REQUESTED` evidence must be
  acknowledged before `WriteExecutionPort.execute()` can run.

P8-S56 does not implement or invoke the EOS command adapter. That integration
remains P8-S57.

## Ordering Contract

The source-backed NSL v0.2 `WriteExecutionCoordinator` enforces:

```text
WriteAttemptRecord
-> WriteEvidencePort.record_requested()
-> matching durable WriteRequestedReceipt
-> checkpoint.write_request_durable = true
-> WriteExecutionPort.execute()
```

An invalid type, mismatched record hash, non-durable receipt, or receipt whose
timestamp predates the request blocks provider invocation. The platform
adapter preserves this contract and does not create a second write hash rule.
The canonical NSL `WriteAttemptRecord.record_hash` is stored and reconstructed
with the admitted NSL type on every read.

## Persistence Semantics

The table stores all P8-S56 required references:

- tenant and NSL execution identity;
- business operation, invocation, and write-node identity;
- tool and contract identity;
- approval request identity;
- idempotency key and payload hash;
- write-intent hash and precondition evidence identity;
- requested, persisted, and canonical record-hash evidence.

`(tenant_id, nsl_execution_id, invocation_id)` is the write-attempt primary
identity. `(tenant_id, record_hash)` is also unique.

```text
new attempt identity
-> append one WRITE_REQUESTED row
-> return durable receipt

same attempt identity + exact same record
-> return the original durable receipt

same attempt identity + changed semantics or timestamp
-> fail closed as conflict

new invocation + same NSL idempotency identity
-> append a distinct attempt row
```

The last case is intentional. P8-S55 owns execution-level idempotency
reservation, while P8-S56 records each actual provider invocation attempt.
EOS remains the authoritative business idempotency owner. The P8-S57 adapter
must forward the existing idempotency key and payload hash without deriving
new values.

Persisted rows are append-only through this adapter. It exposes record and read
operations only; no update or delete API exists. Invalid NSL types, clock
inversion, durable-row tampering, incompatible receipt types, conflicts, and
database failure all fail closed with typed and sanitized AE errors.

## PostgreSQL Migration

Migration `2507_ae_nsl_write_evidence` was applied to the actual
`nex_ae_test` database. The table name is 21 characters and no cross-database
foreign key or EOS SQL was introduced.

The protected PostgreSQL smoke proved:

- eight concurrent writes converged to one durable row and one receipt;
- all receipts used the exact NSL record hash;
- restart replay returned the original durable receipt;
- persisted time was not earlier than requested time;
- protected smoke cleanup removed only its tenant-scoped probe row.

An additional isolated-wheel smoke used the actual admitted NSL v0.2
`WriteAttemptRecord` and `WriteRequestedReceipt` types against `nex_ae_test`.

## NSL Release Admission

The NSL source and wheel content remain unchanged:

- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- source-tree digest:
  `e7ffb07378ba01f4c9da6645f91b75614c605907`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- wheel size: `194308` bytes

The admitted public surface is now 22 symbols:

- release admission hash:
  `sha256:0b3bd9a82bf36cceb3b4e9697166ebb8b42c028c21d994f7a39a103b445737a2`
- adapter contract hash:
  `sha256:d97f1708cb3b622b284c0e03dba3fcc6c70ac3e3ff6adc52ded05845565a5027`

Reproducible wheel admission, isolated installed-package readiness, and the
protected P8-S06 compatibility smoke passed. The host NSL v0.1 installation
was preserved.

## Verification

- S56 focused unit tests: `37 passed`.
- S56 module coverage: statement `100%`, branch `100%`.
- P8-S01 through P8-S06 and S52 through S56 focused regression:
  `241 passed`, `4 protected skips`.
- Migration runner and S131 dynamic inventory regression: `22 passed`.
- Actual `nex_ae_test` PostgreSQL concurrency/restart smoke: `1 passed`.
- Actual admitted NSL v0.2 wheel with `nex_ae_test`: `1 passed`.
- Protected P8-S06 source-backed compatibility smoke: `8/8 passed`, zero EOS
  mutations.
- AE Slice Gate: `4,902 passed`, `27 skipped`.
- AE Slice Gate coverage: statement `98.39%`, branch `96.31%`.
- New write-evidence module and expanded public-API adapter: statement `100%`,
  branch `100%` each.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.

## Exit Decision

P8-S56 is closed. P8-S57 may implement the EOS-backed NSL
`WriteExecutionPort` adapter, but it must remain behind the durable evidence
receipt and must not embed EOS SQL, bypass EOS APIs, or recalculate write
identity. Remote model providers were not required for this Slice.
