# P8-S55: Durable NSL IdempotencyEvidencePort

## Status

Completed on 2026-10-22.

## Scope

- Added the AE-owned `ae_nsl_idem_evidence` PostgreSQL source of record.
- Added `SqlAlchemyNslIdempotencyEvidencePort` over the admitted NSL v0.2
  `IdempotencyEvidencePort` contract.
- Admitted the public `IdempotencyEvidencePort`, `IdempotencyEvidenceRecord`,
  `IdempotencyReservation`, and `IdempotencyDisposition` symbols.
- Preserved the NSL rule that `IdempotencyKey` and `PayloadHash` are distinct.

## Atomic Reservation Semantics

The adapter uses `(tenant_id, idempotency_key)` as its primary reservation
identity and also protects `(tenant_id, business_operation_id, write_node_id)`
with a unique constraint.

```text
new key + payload
-> CREATED

same tenant/key + same payload and identity
-> REUSED

same tenant/key + different payload
-> CONFLICT

same business operation/write node + different key
-> CONFLICT
```

`INSERT ... ON CONFLICT DO NOTHING` followed by an in-transaction read provides
one durable winner under concurrent PostgreSQL reservations. The first record
is integrity-bound with a semantic SHA-256 hash. Persisted tampering, malformed
NSL types, unavailable storage, and incompatible reservation types fail closed
with typed, sanitized AE errors.

PostgreSQL may return `TIMESTAMPTZ` in the database session timezone. The
adapter keeps the NSL input contract UTC-only and normalizes timezone-aware
database values back to UTC before integrity verification.

## Two Idempotency Layers

This table is NSL execution idempotency evidence only. It does not replace or
write EOS authoritative business idempotency state.

```text
AE / NSL execution reservation
AND
EOS canonical command idempotency
```

Both layers must receive the same actual `IdempotencyKey` and `PayloadHash`.
The NSL reservation currently returns no `business_result_ref`; the EOS command
boundary remains authoritative for an original business result on replay.
P8-S57 must pass the already-created identity to EOS without recalculation.

## Persistence

Migration `2506_ae_nsl_idempotency_evidence` was applied to the actual
`nex_ae_test` database. The table name is 20 characters and contains:

- tenant, business operation, and write-node identity;
- tool and contract identity;
- idempotency key and payload hash;
- provider guarantee reference and retention horizon;
- evidence integrity hash and creation timestamp.

No foreign key to EOS and no cross-database SQL were introduced.

## NSL Release Admission

The NSL source and wheel content remain unchanged:

- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- source-tree digest:
  `e7ffb07378ba01f4c9da6645f91b75614c605907`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- wheel size: `194308` bytes

The admitted public surface changed to 19 symbols:

- release admission hash:
  `sha256:82fb507b183f886ac3308a607d300477380c1471ad0a134162e13ca3b15ed571`
- adapter contract hash:
  `sha256:ee90a9e23fe69552ef3ece510193a95687eaa0e15058c8de60c4fc44e4ebd7d8`

Reproducible wheel admission, isolated installed-package readiness, and the
protected P8-S06 compatibility smoke passed. The host NSL v0.1 installation
was preserved.

## Verification

- S55 focused tests: `25 passed`.
- S55 module coverage: statement `100%`, branch `100%`.
- P8-S01 through P8-S06 and S52 through S55 focused regression:
  `197 passed`, `1 protected skip`.
- Migration runner and S131 dynamic inventory regression: `26 passed`.
- Actual `nex_ae_test` PostgreSQL smoke: `1 passed`.
- PostgreSQL smoke proved 8-way concurrency as `1 CREATED + 7 REUSED`, restart
  replay as `REUSED`, changed payload as `CONFLICT`, and one durable row.
- Actual admitted NSL v0.2 wheel types with `nex_ae_test`: passed.
- Protected P8-S06 source-backed compatibility smoke: `8/8 passed`, zero EOS
  mutations.
- AE Slice Gate: `4,864 passed`, `25 skipped`.
- AE Slice Gate coverage: statement `98.37%`, branch `96.29%`.
- Expanded public-API adapter: statement `100%`, branch `100%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.

## Exit Decision

P8-S55 is closed. P8-S56 may add durable `WRITE_REQUESTED` evidence before any
provider or EOS invocation while reusing the reservation identity established
here. Remote model providers were not required for this Slice.
