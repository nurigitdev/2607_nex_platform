# P8-S58: Fresh EOS Business Authorization

## Status

Completed on 2026-10-22.

## Scope

P8-S17 and P8-S19 already placed the EOS-owned
`finance:voucher-draft:create` authorization check after canonical payload
validation and before the authoritative business transaction. P8-S58 keeps
that structure and closes the remaining freshness and acceptance evidence:

- EOS requests current effective authorization from OA for every command,
  including an idempotent replay;
- an upstream NSL WriteGuard ALLOW cannot replace or override that EOS check;
- current DENY and unavailable authority fail closed before the EOS
  coordinator or any voucher mutation runs;
- the OA effective-authorization read and the EOS client request both declare
  the response non-cacheable;
- the accepted OA revision hash and EOS check time remain part of the durable
  BusinessOperation result metadata.

No table, migration, public payload field, or operation identity changed.

## Freshness Boundary

`HttpOaAuthorizationSource` now sends:

```text
Cache-Control: no-store, max-age=0
Pragma: no-cache
```

The OA effective-authorization endpoint returns the same directives. EOS does
not cache a prior ALLOW and does not use the upstream WriteGuard decision as a
business authorization source. Each invocation resolves active membership,
the exact tenant and subject, `finance:voucher-draft:create`, revision hash,
and any supplied project, organization, and resource constraints.

Authorization remains outside the EOS database transaction so a slow OA call
does not hold a database transaction open. It is nevertheless performed after
payload admission and immediately before the coordinator is entered. A replay
therefore rechecks current authority before EOS may disclose the prior result.

## Regression Evidence

The focused SQLite test exercises one canonical post-WriteGuard command across
three current authorization states:

1. current DENY returns `EOS_AUTHORIZATION_DENIED` with zero BusinessOperation,
   idempotency, voucher, and outbox rows;
2. current ALLOW creates exactly one committed voucher operation;
3. authority revoked before an exact replay returns 403 and leaves every row
   count unchanged.

The authorization source call sequence is asserted as
`DENY -> ALLOW -> DENY`, proving that the replay did not reuse the accepted
revision from the original commit.

## PostgreSQL Evidence

The protected smoke connected as `nex_eos_user` to `nex_eos_test`, verified
the current migration head includes `2508_eos_operation_name_compatibility`,
and repeated the deny, allow, and revoked-replay sequence through the protected
EOS FastAPI route.

The smoke uses the real EOS PostgreSQL repositories and transaction
coordinator with a controllable current-authorization source. OA HTTP request
and response cache directives are verified separately at the transport route
tests; this Slice does not require a second OA database mutation or a remote
model provider.

Tenant-scoped cleanup completed with zero residual rows.

## Verification

- Focused P8-S58 and relevant S17/S19/S57/OA regression: `106 passed`.
- Actual `nex_eos_test` PostgreSQL protected smoke: `1 passed`.
- EOS Slice Gate: `372 passed`, `12 skipped` protected smokes.
- EOS Slice Gate statement coverage: `99.80%`.
- EOS Slice Gate branch coverage: `100.00%`.
- `authorization.py` statement and branch coverage: `100%`.
- Contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.

## Exit Decision

P8-S58 is closed. EOS now has explicit no-cache current business authorization
semantics and executable evidence that upstream ALLOW, prior commit, or exact
replay cannot override a current OA/EOS DENY. P8-S59 may map the raw EOS result
into the admitted NSL commit-outcome types without changing this boundary.
