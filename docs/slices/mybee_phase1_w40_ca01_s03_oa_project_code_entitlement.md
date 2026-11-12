# W40-CA01-S03 OA Project-Code Entitlement

## Status

`CLOSED` on 2026-11-12.

This Slice establishes OA as the decision authority for Project-scoped access
without moving EOS Project or membership ownership into OA. EOS remains the
business source of truth; OA stores a versioned, revocable authorization
projection keyed by the human-readable Project Code.

## Implemented Boundary

- Added the exact grant identity `(tenant_id, project_code, subject_id)`.
- Added idempotent source-event replay, monotonic source-version updates,
  event collision rejection, revocation, and tenant isolation.
- Added `POST /internal/v1/auth/project-decisions` with required service scopes
  `service:call` and `authorization:read`.
- Decisions require exact tenant, subject, Project Code, action, active OA
  membership, fresh Project projection, admitted Project role, and applicable
  global OA scope.
- `INACTIVE` and `CLOSED` Projects deny all actions. `CLOSING` permits only the
  fixed read/report action subset needed to close a Project.
- Unknown actions, stale projections, revoked grants, missing grants, and
  malformed authorization projections fail closed with explicit reason codes.
- Responses are deterministic, non-cacheable, and contain projection lineage
  rather than EOS membership payloads or private identity attributes.

The admitted action matrix covers Project read/membership/work-assignment and
MyBee voucher/report actions. This Slice intentionally exposes no manual grant
mutation API: W40-CA01-S04 owns authenticated EOS outbox to OA inbox delivery.

## Persistence And Contracts

Migration `2518_oa_project_grant.sql` adds `oa_project_grant` with a composite
Project-Code identity, tenant foreign key, unique source event, monotonic source
version, role/status constraints, and query indexes.

Added artifacts:

- request and response JSON schemas;
- positive allow examples and private-field negative examples;
- OA OpenAPI operation and security metadata;
- source-backed OA schema inventory expectation;
- refreshed MyBee platform lock and migration-head manifest.

## Reliability Correction

Branch hardening exposed that frozen `OaAuthorizationError` instances could not
cross SQLAlchemy's generator transaction context because Python attempted to
attach traceback state. The repository now captures authorization rejection
inside the transaction and raises it after the context exits. Integrity and
database failures continue to map to typed `409` and `503` outcomes.

## Validation Evidence

Focused contract and OA audit regression:

```text
46 passed, 1 protected skip
contract validation: PASS (241 schemas, 299 positive, 250 negative, 10 OpenAPI)
```

Protected actual `nex_oa_test` PostgreSQL migration/restart/decision smoke:

```text
1 passed
migration 2518 applied in a temporary schema
grant persisted and read through a restarted repository
authorization decision: ALLOW
temporary schema residue: 0
```

NeX-OA Slice Gate:

```text
status: PASS
commands: 5/5
tests: 1168 passed, 12 protected skips
statement coverage: 96.98%
branch coverage: 95.62%
project_entitlements.py: 100.00% statement / 100.00% branch
```

Schema/API Checkpoint Gate:

```text
status: PASS
commands: 6/6
tests: 20865 passed, 157 protected skips
statement coverage: 98.55%
branch coverage: 97.12%
project_entitlements.py: 100.00% statement / 100.00% branch
contract, Golden Journey, and demo-to-product dependency audits: PASS
```

Machine-readable evidence:

- `reports/quality/mybee-w40-ca01-s03.coverage.json`
- `reports/quality/mybee-w40-ca01-s03-checkpoint.coverage.json`

## Preserved Boundaries

- EOS remains SoR for Project lifecycle, approved parties, and memberships.
- OA is SoR for the current authorization decision and its delivered
  Project-code entitlement projection.
- UUIDs remain internal technical identities; API authorization is expressed
  with Project Code.
- Tokens do not embed Project membership lists.
- No remote model provider is required.

## Next Entry

`W40-CA01-S04` delivers EOS Project lifecycle and membership outbox events to
the OA projection with restart-safe inbox, replay, revocation, and repair.
