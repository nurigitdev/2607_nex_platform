# W40-CA01-S04 EOS Outbox and OA Inbox Entitlement Synchronization

## Status

`CLOSED` on 2026-11-12.

This Slice makes the approved EOS Project membership snapshot an authenticated,
restart-safe OA authorization projection. EOS remains the Project and membership
source of truth; OA remains the authorization decision source of truth.

## Implemented Boundary

- Final Project approval now appends `PROJECT_ENTITLEMENT_SNAPSHOT` in the same
  EOS transaction as Project, membership, and Project Agent lifecycle creation.
- The deterministic event contains the exact normalized member snapshot,
  Project Code, lifecycle status, source version, correlation/causation lineage,
  and semantic payload hash.
- EOS records `authorization_version` and
  `authorization_sync_state=PENDING`; an exact OA ACK changes the state to
  `IN_SYNC`.
- The installed EOS outbox publisher routes Project Agent lifecycle events to AE
  and entitlement snapshots to OA with separate signed service tokens.
- OA admits only `nex-eos` with `service:call` and
  `project-entitlement:write`, verifies the tenant and hash bindings, applies the
  whole snapshot transactionally, and returns an event/version/hash-bound ACK.
- Exact replay is a no-op. Changed replay, stale or conflicting versions,
  unsupported event types, tenant mismatch, hash mismatch, and malformed member
  snapshots fail closed.
- Terminal OA validation failures leave the outbox replayable but expose
  `authorization_sync_state=FAILED`; a later valid replay can recover to
  `IN_SYNC`. Unconfirmed or malformed ACKs retain the historical retry-required
  behavior.

## Persistence and Contracts

- EOS migration `2538_eos_project_authorization_sync.sql` adds synchronization
  state/version to `eos_project`; no additional EOS event table was introduced.
- OA migration `2519_oa_project_entitlement_inbox.sql` adds the single
  `oa_project_entitlement_inbox` table. Event uniqueness moved from individual
  grants to this inbox so one snapshot event can own multiple member grants.
- Existing `eos_outbox` and `oa_project_grant` tables remain authoritative and
  are reused.
- Added canonical event/receipt JSON schemas, positive and negative examples,
  the OA OpenAPI operation, trust scope, migration-head manifest, and MyBee
  platform lock refresh.

## Validation Evidence

Focused EOS/OA regression:

```text
focused S04 + S80 compatibility: 71 passed, 1 protected skip
trust/bootstrap regression: 84 passed
baseline/lock regression: 17 passed
contract validation: PASS (243 schemas, 301 positive, 252 negative, 10 OpenAPI)
```

Actual `nex_eos_test` and `nex_oa_test` PostgreSQL protected smoke:

```text
35 passed
database/user identity: verified for both test databases
migrations: EOS 2538 and OA 2519 applied in isolated schemas
snapshot apply, ACK, exact replay, stale rejection, version 2 replacement: PASS
EOS authorization state: IN_SYNC
temporary schema residue: 0
```

NeX-OA Slice Gate:

```text
status: PASS
commands: 6/6
tests: 1203 passed, 12 protected skips
statement coverage: 97.06%
branch coverage: 95.72%
project_entitlement_sync.py: 100.00% statement / 98.57% branch
```

NeX-EOS Slice Gate:

```text
status: PASS
commands: 6/6
tests: 1525 passed, 45 protected skips
statement coverage: 96.35%
branch coverage: 94.08%
project_entitlement_events.py: 100.00% statement / 100.00% branch
oa_outbox_transport.py: 100.00% statement / 100.00% branch
```

Machine-readable evidence:

- `reports/quality/mybee-w40-ca01-s04-oa.coverage.json`
- `reports/quality/mybee-w40-ca01-s04-eos.coverage.json`

## Preserved Boundaries

- Project UUID remains internal lineage; authorization requests and grants use
  the human-readable Project Code.
- OA does not become Project membership SoR, and tokens do not embed membership
  lists.
- S04 delivers initial approved membership synchronization and the generic
  version/replay foundation. Lifecycle-driven revocation and reconciliation
  remain owned by W40-CA01-S06.
- No remote model provider is required.

## Next Entry

`W40-CA01-S05` connects Project-Code authorization decisions to the intended
MyBee accounting entry points without bypassing OA.
