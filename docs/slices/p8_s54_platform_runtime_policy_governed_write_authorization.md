# P8-S54: Platform RuntimePolicy / GovernedWrite Authorization Adapter

## Status

Completed on 2026-10-22.

## Scope

- Admitted the NSL v0.2 public `RuntimePolicyPort`, `WritePolicyRequest`,
  `PolicyDecision`, and `PolicyEffect` types without importing private NSL
  modules from production Platform code.
- Added a dedicated AE `PlatformRuntimePolicyAdapter` over a
  `GovernedWriteAuthorizationSource`.
- Validated the Frozen `GovernedWriteAuthorization`,
  `ProtectedOperationDescriptor`, and `OperationTrustDecision` shapes before
  projecting authority into an exact NSL `PolicyDecision`.
- Kept the existing AE model-selection `runtime_policy.py` separate because it
  has different ownership and semantics.

## Authorization Conjunction

An NSL policy ALLOW now requires all applicable S54 controls:

```text
current OA ALLOW
AND exact tenant binding
AND exact BusinessOperationId binding
AND protected operation capability = WRITE
AND actor binding when actor_ref is present
AND OperationTrustDecision = ALLOW
AND trust fingerprint = protected-operation fingerprint
AND assurance >= required assurance
AND no elevated DUMMY_ALWAYS_ALLOW decision
```

Any valid trust, assurance, or binding denial produces an exact,
request-bound NSL `PolicyDecision(DENY)`. An OA DENY cannot form the Frozen
`GovernedWriteAuthorization` because `oa_allowed` is contractually `true`; it
therefore fails closed before policy projection. Malformed authority, source
failure, incompatible NSL types, or a binding-mutating decision also fails
closed with a typed, sanitized AE error. A single ALLOW cannot override
another required DENY.

The trust timestamps are projected without alteration. The NSL `WriteGuard`
remains responsible for its certified current-time check and rejects future or
expired policy evidence.

## Deferred Provider-Boundary Check

Frozen design explicitly says that `operation_fingerprint` is not the NSL
`PayloadHash` or `write_intent_hash`. The actual `WriteCallRequest` fingerprint
can only be checked at the governed `WriteExecutionPort` immediately before
the provider/EOS call. P8-S54 therefore validates the authority-side
descriptor/trust fingerprint binding but does not invent an NSL fingerprint
mapping. Actual WRITE conformance remains assigned to P8-S57.

P8-S58 fresh EOS/OA business authorization remains an additional mutation-time
control and cannot be replaced by this upstream ALLOW.

## NSL Release Admission

The NSL source and wheel content did not change:

- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- source-tree digest:
  `e7ffb07378ba01f4c9da6645f91b75614c605907`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- wheel size: `194308` bytes

The admitted public symbol set changed, so the semantic identities were
recomputed:

- previous release admission hash:
  `sha256:52c8f502a28b5bd8ba1e2837b9d688744a8dd15b0af057d2d25297b7fadfbc50`
- current release admission hash:
  `sha256:37b1bd2725db30c5170db53682aaa24a062fe7fe971dbe4b0398af6f1771c87b`
- current adapter contract hash:
  `sha256:a6ae7b8e5999cb264a935a9c4313320e97c8cd60d72762c2445d39a37ef0b540`

Reproducible admission built the wheel twice with the same digest. Isolated
installed-package readiness passed while preserving the host NSL v0.1
installation. The actual admitted wheel also produced a request-bound
`PolicyDecision(ALLOW)` through the new adapter.

## Verification

- S54 focused policy tests: `39 passed`.
- S54 module coverage: statement `100%`, branch `100%`.
- P8-S01 through P8-S06, S52, and S54 focused regression: `172 passed`.
- Protected P8-S06 source-backed compatibility smoke: `8/8 passed`.
- AE Slice Gate: `4,840 passed`, `24 skipped`.
- AE Slice Gate coverage: statement `98.37%`, branch `96.29%`.
- Changed runtime-policy and public-API modules: statement `100%`, branch
  `100%` each.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- Ruff and diff checks passed.

## Persistence And Provider Boundary

No database migration, PostgreSQL mutation smoke, or remote model provider is
required by P8-S54. The adapter consumes current Platform authorization from an
injected source. Durable NSL idempotency and WRITE evidence begin in P8-S55 and
P8-S56.

## Exit Decision

P8-S54 is closed. P8-S55 may add durable NSL idempotency evidence while
retaining EOS authoritative business idempotency as a separate layer bound to
the same actual IdempotencyKey and PayloadHash semantics.
