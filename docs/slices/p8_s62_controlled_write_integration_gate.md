# P8-S62: Controlled WRITE Integration Gate

## Status

Completed on 2026-10-22.

## Scope

- Added an AE-owned controlled-WRITE integration facade over the admitted NSL
  v0.2 public API and the Platform adapters completed in P8-S54 through P8-S61.
- Composed the canonical path from valid approval identity through runtime
  policy, `WriteGuard`, durable idempotency reservation, `WRITE_REQUESTED`
  evidence, EOS execution, commit classification, and post-WRITE verification.
- Expanded the admitted NSL public-symbol set with the eight orchestration
  primitives needed to compose that path without importing private NSL code.
- Added deterministic negative and protected PostgreSQL evidence for
  authorization denial, idempotency conflict, payload-hash mismatch, invalid
  Project/Account references, replay, and zero duplicate mutation.
- Ran the repository Full Gate after the protected integration gate.

No database table, migration, public HTTP field, automatic WRITE retry, or
remote model-provider dependency was added.

## Integration Boundary

P8-S53 remains responsible for producing a valid ApprovalEvidence and resume
admission. P8-S62 starts from that admitted approval identity and invokes the
actual NSL v0.2 primitives in this order:

1. bind the ApprovalEvidence to the `WriteIntent`;
2. resolve the Platform governed-WRITE policy and build the NSL policy request;
3. evaluate `WriteGuard` fail-closed;
4. reserve durable idempotency evidence;
5. build the canonical `WriteCallRequest`;
6. persist `WRITE_REQUESTED` before invoking EOS;
7. classify EOS as `COMMITTED`, `NOT_COMMITTED`, or commit-unknown;
8. verify only a committed result against the authoritative EOS read model.

The facade does not catch an ambiguous result, retry CREATE, or reinterpret an
NSL outcome. `NOT_COMMITTED` and commit-unknown outcomes skip verification;
the reconciliation boundary from P8-S60 remains the only path for resolving an
unknown commit.

## NSL Admission

The source and wheel content remain unchanged. Admission now includes
`ProviderIdempotencyEvidence`, `WriteGuard`, `WriteGuardRequest`,
`write_policy_request`, `WriteCallRequestBuilder`,
`WriteExecutionCoordinator`, `PostWriteVerifier`, and `VerificationResult`.

- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- source-tree digest:
  `e7ffb07378ba01f4c9da6645f91b75614c605907`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- admitted public symbols: `38`
- release admission hash:
  `sha256:e9fe0ed301a951ef990a7b2429bee2da3c8d389e7f243e110b9a73e13ec0de5f`
- adapter contract hash:
  `sha256:5ffeabb04b9a060f6b00d03fe7bd2eb827d9839f74e3f84907d1ce585ff58773`

The P8-S06 actual-wheel compatibility smoke passed all eight checks after the
admission update.

## Protected PostgreSQL Evidence

The protected gate loaded the admitted NSL v0.2 wheel ahead of repository
source and verified the exact database identities:

- `nex_ae_test` as `nex_ae_user`;
- `nex_eos_test` as `nex_eos_user`.

It also verified AE migrations `2506_ae_nsl_idempotency_evidence` and
`2507_ae_nsl_write_evidence`, plus EOS migration
`2508_eos_operation_name_compatibility`.

The successful path created exactly one BusinessOperation, idempotency record,
Voucher draft, outbox event, and two Voucher lines. Exact replay returned the
original committed result and changed the NSL reservation from `CREATED` to
`REUSED` without creating a second EOS mutation. Both results were
post-WRITE `VERIFIED`.

The same gate then proved:

- changed payload under the same BusinessOperation is rejected as an
  idempotency conflict before EOS mutation;
- fresh EOS authorization denial maps to `NOT_COMMITTED` and is not verified;
- unknown Project/Account references map to `NOT_COMMITTED` and leave EOS
  counts unchanged;
- a mismatched payload hash is rejected by the actual NSL `WriteIntent` before
  execution;
- tenant-scoped AE and EOS rows are removed and zero residue is verified.

## Verification

- P8-S62 unit and compatibility regression: `50 passed`.
- Integration module unit suite: `16 passed`; statement coverage `100%`, branch
  coverage `100%`.
- Actual admitted NSL v0.2 wheel plus `nex_ae_test` and `nex_eos_test`
  PostgreSQL gate: `1 passed`.
- P8-S06 compatibility smoke: `PASS`, `8/8` checks.
- Repository Full Gate: `16,624 passed`, `82 skipped` protected tests.
- Full Gate statement coverage: `96.80%` against the `95%` threshold.
- Full Gate branch coverage: `96.20%` against the `85%` threshold.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- AE Web regression: `355 passed`, `0 failed`.
- Full Gate operational and closure checks: passed; final exit code `0`.
- Ruff, formatting, and diff checks: passed.

The Full Gate deliberately leaves opt-in protected smokes disabled. The P8-S62
PostgreSQL gate above was enabled and executed separately, so its database
evidence is not inferred from a skipped test.

## Exit Decision

P8-S62 and the P8.5 controlled-WRITE stage are closed. A valid approved WRITE
can now traverse the admitted NSL guard, durable AE evidence boundaries, the
EOS command boundary, and authoritative post-WRITE verification while
preserving idempotency, three-way outcome semantics, and zero duplicate
mutation. The implementation is ready for P8-S63 and the next canonical wave.
