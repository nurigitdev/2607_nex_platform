# W40-CA01-S06 Lifecycle Revocation, Reconciliation, and Protected Gate

## Status

`CLOSED` on 2026-11-12.

This Slice closes the W40 Project entitlement lifecycle by making EOS state
changes produce versioned authorization snapshots, giving operators a signed
EOS-authoritative reconciliation boundary, and proving revocation and repair
against actual EOS and OA PostgreSQL test databases.

## Implemented Boundary

- Approved Project membership add, batch add, removal, and `MEMBER`/`VIEWER`
  role changes emit a new EOS entitlement snapshot and mark synchronization
  `PENDING`.
- Approved Project lifecycle transitions emit the same versioned snapshot, so
  OA observes `ACTIVE`, `INACTIVE`, `CLOSING`, and `CLOSED` authorization state.
- `OWNER` and `MANAGER` role changes remain outside the direct membership route
  and require the governed Project-party workflow.
- Legacy direct-created Projects do not acquire entitlements implicitly. They
  require an explicit audited import boundary.
- EOS exposes a signed internal reconciliation route for the exact
  `(tenant_id, project_id)` authority. OA exposes an EOS-only, signed,
  hash-bound Project Code projection route.
- Reconciliation compares Project identity, immutable Project Code, lifecycle
  status, EOS source version, and the canonical active-membership set.
- Repair never mutates OA directly. EOS appends a fresh authoritative snapshot,
  increments `authorization_version`, and waits for the existing outbox/inbox
  delivery and acknowledgement path.
- An acknowledgement-only pending state remains `ACK_PENDING`; it does not
  manufacture another authority version.
- HTTP failure, malformed or tampered projection, stale version, missing
  Project, legacy Project, memberless authority, and concurrent version changes
  fail closed.

## Contracts And Persistence

- Added `oa_project_entitlement_projection_request.v1` and
  `oa_project_entitlement_projection.v1` schemas, examples, negative fixtures,
  and the matching NeX-OA OpenAPI route.
- Added canonical operations `PROJECT.MEMBERSHIP.CHANGE_ROLE` and
  `PROJECT.AUTHORIZATION.RECONCILE`.
- Reused `eos_project`, `eos_project_member`, the existing EOS outbox, OA inbox,
  and OA Project grant projection. No database table or migration was added.
- EOS remains Project and membership SoR. OA remains authorization decision SoR.
- No embedding, reranker, or generation provider is required.

## Validation Evidence

Focused regression and contract validation:

```text
focused lifecycle/contract/gate regression: 55 passed, 1 protected skip
contract validation: PASS
schemas=245 examples=303 negative_examples=254 openapi=10
```

Actual `nex_eos_test` and `nex_oa_test` PostgreSQL protected smoke:

```text
status: PASS
database/user identity: nex_eos_test/nex_eos_user and nex_oa_test/nex_oa_user
migrations: applied in isolated schemas
signed OA projection and signed EOS reconciliation: verified
membership drift: detected
EOS-authoritative repair snapshot and OA convergence: verified
MEMBER -> VIEWER role change: propagated
member removal and revocation: propagated
ACTIVE -> INACTIVE lifecycle revocation: propagated
final reconciliation: IN_SYNC
temporary schema residue: 0
```

NeX-EOS Slice Gate:

```text
status: PASS
commands: 5/5
tests: 1624 passed, 48 protected skips
statement coverage: 96.83%
branch coverage: 95.10%
previous EOS baseline: 95.06% branch coverage
project_entitlement_reconciliation_api.py: 100% statement / 100% branch
project_entitlement_state.py: 100% statement / 100% branch
project_entitlement_reconciliation.py: 99% statement / 100% branch
```

NeX-OA Slice Gate:

```text
status: PASS
tests: 1240 passed, 14 protected skips
statement coverage: 96.65%
branch coverage: 95.08%
```

Machine-readable evidence:

- `reports/quality/w40-ca01-s06-eos-slice-gate.json`
- `reports/quality/w40-ca01-s06-oa-slice-gate.json`

## W40 Entry Decision

The W40 Project entitlement amendment is closed. Project membership and
lifecycle mutations now have an EOS-authoritative, versioned, revocable,
reconcilable, and protected EOS-to-OA path. Subsequent accounting work may rely
on fail-closed Project Code authorization without introducing another
membership authority.
