# W60-S7-02F Project P&L Query API and MyBee Consumer

## Status

- Slice: `W60-S7-02F`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Date: 2026-11-15
- Owners: NeX-EOS, NeX-MyBee

## Decision

This Slice exposes the immutable Project P&L projection built by
W60-S7-02 through W60-S7-02E without creating another read model or database
table. NeX-EOS remains the projection system of record and MyBee consumes a
strict, owner-scoped contract.

Every query performs a fresh OA Project authorization check for
`finance:report:read` before reading the projection. A signed service token is
also required at the EOS boundary. Missing authority, unavailable authority,
tenant drift, and projection identity drift fail closed.

The initial consumer returns Project aggregate and classified component data.
It deliberately does not expose employee, salary, payroll-person, or source
document payloads. Advanced small-cell suppression, differential disclosure,
and audience-specific presentation policy remain controlled work for S7-03;
this Slice does not claim that privacy closure.

## EOS Query Boundary

The admitted operation is:

```text
GET /internal/v2/finance/projects/{project_id}/pnl/{period_id}
operation_id = FINANCE.PROJECT_PNL.GET
```

Required request context:

- `X-NeX-Tenant-Id`
- `X-NeX-Company-Id`
- `X-NeX-Subject-Id`
- `X-NeX-Correlation-Id`
- signed service bearer token

An optional positive `projection_version` selects an immutable historical
version. Omitting it returns the latest persisted projection. Successful and
error responses are marked `Cache-Control: no-store, max-age=0` and
`Pragma: no-cache`.

`EosProjectPnlQueryService` reuses:

- `EosProjectAuthorizationGate` for fresh Project authority;
- `SqlAlchemyEosProjectPnlRepository` for latest/versioned reads;
- canonical `eos_project_pnl_projection.v1` serialization.

No migration or mutable query-side cache was added. The EOS contract catalog
version is `mybee-w60-s7-02f` and the OpenAPI version preserves the historical
P8 compatibility prefix.

## MyBee Consumer

`NexProjectPnlClient` and `HttpProjectPnlProviderTransport` provide a strict
consumer boundary for MyBee. Admission verifies:

- exact response fields and schema name;
- tenant, company, Project UUID, Project Code, period, currency, and requested
  projection version;
- positive version, timezone-aware timestamps, classification vocabulary, and
  immutable hashes/watermarks;
- component totals against direct, allocated, committed, and residual rollups;
- total revenue, cost, and profit arithmetic;
- aggregate-only privacy surface with no employee or salary fields.

Caller argument errors remain `400`. Provider HTTP problems, malformed JSON,
contract drift, arithmetic drift, and identity drift are separated into
fail-closed consumer errors. The admitted projection is exposed through
immutable mappings and tuples.

## Verification

Focused SQLite regression and branch hardening:

```text
179 passed
new EOS query service/API coverage=100% statement/branch
new MyBee consumer coverage=100% statement/branch
```

Protected PostgreSQL smoke against the actual `nex_eos_test` database:

```text
1 passed
database=nex_eos_test
user=nex_eos_user
```

The smoke created an isolated schema, applied EOS migrations through `2547`,
persisted an immutable P&L projection, authorized a real query, admitted the
response through the MyBee consumer, verified the private-field exclusion, and
removed the schema with zero residue.

Final NeX-EOS Slice Gate:

```text
2281 passed, 64 skipped
statement_coverage=97.04% (threshold 95.00%)
branch_coverage=95.35% (threshold 94.00%)
contract_validation=pass schemas=264 examples=315 negative_examples=257 openapi=10
golden_journey_transition_audit=pass
demo_product_dependency_audit=pass
tiered_quality_gate=pass commands=6/6
```

Evidence: `reports/quality/mybee_phase1_w60_s7_02f_slice_gate.json`.

Remote model providers were not required. The pre-existing non-blocking
Starlette/httpx deprecation warning remains.
