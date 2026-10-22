# P8-S57: EOS WriteExecutionPort Adapter

## Status

Completed on 2026-10-22.

## Scope

- Added an AE-owned implementation of the admitted NSL v0.2
  `WriteExecutionPort` protocol.
- Connected the port only to the EOS canonical
  `POST /internal/v1/finance/voucher-drafts` API.
- Admitted `WriteCallRequest` through the existing NSL v0.2 wheel boundary.
- Preserved the NSL-issued `BusinessOperationId`, `IdempotencyKey`, and
  `PayloadHash` without deriving replacement identities.
- Added protected actual-wheel and `nex_eos_test` PostgreSQL HTTP evidence.

This Slice does not map an EOS response into `WriteCommitted`,
`WriteNotCommitted`, or `WriteCommitUnknown`. That remains P8-S59. It also
does not add a database table or migration.

## Command Projection

`WriteCallRequest.arguments` is the complete canonical EOS business payload.
Every admitted value is unwrapped from its NSL `ValueEnvelope`, converted only
from immutable mappings/tuples into JSON objects/arrays, and validated with the
frozen NSL v0.2 payload-hash algorithm.

The adapter then adds exactly four transport-level fields:

```text
business_operation_id <- WriteCallRequest.business_operation_id
idempotency_key        <- WriteCallRequest.idempotency_key
payload_hash           <- WriteCallRequest.payload_hash
trace                   <- named identities already present in trace_refs
```

It neither imports EOS persistence code nor normalizes business values. It
rejects a different tool, incomplete/extra business fields, tenant or approval
lineage drift, a hash mismatch, and a non-JSON value before network dispatch.

The EOS trace projection requires one valid value for each of:

```text
trace_id:<value>
correlation_id:<value>
causation_id:<value>
```

Unrelated evidence references may coexist in `trace_refs`. Duplicate,
malformed, or missing EOS trace identities fail closed. The adapter never
invents a trace identity from local time or random data.

## HTTP and Trust Boundary

The default endpoint is `NEX_EOS_BASE_URL`, port `8107`, with a 15-second
`NEX_AE_EOS_WRITE_TIMEOUT_SECONDS` default. AE obtains a service token for the
exact `nex-eos` audience from `NEX_AE_TO_EOS_SERVICE_TOKEN` in signed profiles.
`TEST_MOCK` remains available only through the existing explicit test profile.

The adapter sends tenant, invocation, and caller metadata in bounded headers.
It does not retry a command. Timeout and connection loss are raised as the
native categories that the NSL coordinator classifies as an uncertain provider
invocation.

EOS `200` and `201` responses must echo the exact NSL identity and match the
`REPLAYED` and `CREATED` HTTP status pairing. A mismatched or malformed success
is marked outcome-uncertain. A received EOS problem response is preserved as a
typed raw response for the P8-S59 outcome mapper.

## NSL Admission

The NSL source and wheel content did not change:

- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- source-tree digest:
  `e7ffb07378ba01f4c9da6645f91b75614c605907`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- wheel size: `194308` bytes

The admitted public surface is now 23 symbols:

- release admission hash:
  `sha256:20a09b548b30de316ebb913071eb55630565c89e11d8d70039c1b56bccb39850`
- adapter contract hash:
  `sha256:30322825b47609b133f64d00db323cd19803a8fc3c6760b523cf8e7269e3af4f`

Reproducible wheel admission and isolated installed-package readiness passed.
The host NSL v0.1 installation remained unchanged.

## PostgreSQL Evidence

The protected smoke used
`nex_eos_user@nex_eos_test`, verified migration
`2508_eos_operation_name_compatibility`, and exercised the EOS FastAPI command
route through an ASGI HTTP transport.

It proved:

- service-token admission for audience `nex-eos`;
- one canonical voucher commit from the AE NSL adapter;
- an exact replay returning the original business result;
- one BusinessOperation, idempotency record, voucher, and outbox event;
- two balanced voucher lines;
- unchanged NSL operation, idempotency, and payload-hash identities;
- two fresh EOS authorization evaluations, one per request;
- tenant-scoped cleanup with zero residual rows.

No embedding, reranking, or generation provider was required.

## Verification

- Focused S57 adapter tests: `40 passed`.
- P8-S01 through P8-S06 and P8-S52 through P8-S57 focused regression:
  `272 passed`.
- Actual admitted NSL v0.2 `WriteCallRequest` adapter smoke: `1 passed`.
- Actual `nex_eos_test` PostgreSQL HTTP commit/replay smoke: `1 passed`.
- AE Slice Gate: `4,982 passed`, `29 skipped`.
- AE Slice Gate coverage: statement `98.38%`, branch `96.32%`.
- New EOS adapter coverage: statement `96.34%`, branch `98.28%`.
- Expanded public-API adapter and service-auth coverage: statement `100%`,
  branch `100%` each.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.

## Exit Decision

P8-S57 is closed. The EOS command boundary now implements the NSL
`WriteExecutionPort` without bypassing EOS, embedding EOS SQL, inventing an
idempotency key, or recalculating business-operation identity. P8-S58 may
harden fresh EOS business authorization, and P8-S59 may map these raw command
responses into the admitted NSL commit outcomes.
