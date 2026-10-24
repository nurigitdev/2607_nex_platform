# P8-S84: Trust / Authorization Revocation

## Status

Completed on 2026-10-24. P8-S85 is next.

## Boundary

P8-S84 verifies that current trust and authorization are evaluated at the
existing protected boundaries:

```text
NSL package trust invalid
-> isolated installed-package readiness FAIL
-> enabled Agent Runtime worker startup denied
-> no NSL public API activation

approval:decide revoked after WorkItem creation
-> fresh OA authorization lookup
-> WC decision denied
-> WorkItem remains PENDING
-> no Decision / approval outbox

finance:voucher-draft:create revoked after approval
-> fresh OA authorization lookup at EOS
-> EOS command denied before transaction coordinator
-> no attachment resolver call
-> no BusinessOperation / idempotency / Voucher / EOS outbox

OA browser session revoked
-> fresh OA session introspection
-> private attachment content denied
-> no repository / RustFS read
```

Package trust remains a startup/readiness boundary. WC decision authority and
EOS finance authority remain per-action boundaries. Attachment content remains
behind current OA session admission. No cached upstream approval or stale
session is accepted as authority for a new protected action.

## Implementation

The source audit confirmed that production ordering already matches the S84
contract:

- Agent Runtime validates exact installed NSL package readiness before enabling
  an in-process backend.
- `ApprovalDecisionService` obtains fresh OA evidence before committing a
  Decision and outbox event.
- `EosCreateVoucherDraftService` obtains fresh OA evidence before entering its
  business transaction and before resolving attachment references.
- AE attachment content routes introspect OA cookie sessions before owner
  repository or object-storage access.

S84 therefore adds focused regression and protected evidence rather than a new
runtime abstraction, database table, migration, or API field.

## Protected Evidence

The protected acceptance used actual:

```text
nex_ae_test PostgreSQL
nex_wc_test PostgreSQL
nex_oa_test PostgreSQL
nex_eos_test PostgreSQL
rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
digest-admitted nex-skill-language 0.2.0 wheel in an isolated install
```

The test first admitted the exact wheel/lock and then changed only the lock's
wheel digest. The tampered lock failed installed-package readiness and worker
startup. It then used live HTTP authorization lookups against actual OA state
while revoking scopes directly at the fault boundary.

Observed result:

```text
protected tests                         = 1 passed / 0 skipped
valid admitted-wheel readiness          = PASS
tampered package readiness              = FAIL
worker startup with invalid trust       = denied
approval WorkItems                      = 2
approval Decisions after revocation     = 1 (pre-revocation only)
approval outbox rows                    = 1 (pre-revocation only)
revoked finance request status          = 403
AE attachment resolver calls            = 0
EOS BusinessOperation rows              = 0
EOS idempotency rows                     = 0
EOS Voucher rows                         = 0
EOS Voucher attachment rows              = 0
EOS outbox rows                          = 0
revoked-session content status          = 401
RustFS reads after protected revocations = 0
RustFS object-version drift              = 0
test DB/object residue                   = 0
```

Remote generation, embedding, and reranking providers were not required.

## Regression And Quality Gate

Focused S84 regression:

```text
4 passed
1 protected opt-in skipped
```

P8 focused regression:

```text
1,762 passed
59 protected opt-in skipped
```

NeX-AE Slice Gate:

```text
pytest              = 5,359 passed / 45 protected opt-in skipped
statement coverage  = 98.32% / required 95.00%
branch coverage     = 96.28% / required 94.00%
contract validation = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate commands       = 3 / 3
gate exit           = 0
```

The NeX-AE coverage numerator and denominator are exactly unchanged from
P8-S83: 32,399 of 32,954 statements and 10,412 of 10,814 branches. S84 adds
cross-service fault evidence without lowering the owning-service baseline.

## Exit Decision

P8-S84 closes INV-14 for package admission, approval decision, finance
mutation, and protected attachment access. Revoked trust is not converted into
a retryable provider failure, stale upstream approval is not reused, and no
unauthorized database or object-storage mutation occurs. P8-S85 may now execute
the tamper and cross-tenant matrix.
