# P8-S95: Project Membership Lifecycle and Idempotency

## Status

Completed on 2026-10-25.

## Scope

P8-S95 hardened the S94 repository into the deterministic Project membership
lifecycle defined by P8-CA04. It added no table, migration, public route, OA
scope, NSL source, or Voucher policy.

## Accepted Lifecycle

```text
ABSENT  -> ACTIVE  through ADD
ACTIVE  -> ACTIVE  through same-role replay
ACTIVE  -> REMOVED through REMOVE
REMOVED -> REMOVED through terminal replay
REMOVED -> ACTIVE  through same-role reactivation
```

One `(tenant_id, project_id, subject_id)` row is reused throughout the
lifecycle. Its stable membership ID is preserved and its version advances only
for a real state transition. A requested role that differs from the existing
role fails closed; P8.10 does not invent an implicit role-change operation.

An ACTIVE Project cannot lose its final active OWNER. An INACTIVE Project may
complete removal because it no longer requires an operational owner.

## Concurrency Boundary

Every lifecycle mutation locks the same tenant-scoped EOS Project row before
reading or changing membership state. This serializes mutations within one
Project while allowing unrelated Projects to proceed independently. The
membership update also carries status/version predicates and returns a typed
version conflict if its optimistic guard loses.

No lock table or duplicate membership history table was introduced. Later
governed operations retain mutation audit in the existing EOS
BusinessOperation/outbox lineage.

## Verification

Focused SQLite lifecycle and error regression:

```text
31 passed
statement coverage = 100%
branch coverage    = 100%
```

Actual `nex_eos_test` PostgreSQL protected smoke:

```text
4 concurrent same-subject ADD calls -> one stable membership ID
2 concurrent OWNER removals         -> one REMOVED / one LAST_OWNER_REQUIRED
active OWNER count after race       -> 1
cleanup residue                     -> 0
result                              -> 1 passed / 0 skipped
```

EOS regression:

```text
642 passed
20 expected protected skips
0 failed
```

## Exit Decision

P8-S95 is closed. Membership lifecycle, replay, reactivation, version guard,
tenant isolation, and last-active-OWNER protection are ready for the governed
service/API and OA-backed authorization boundary in P8-S96.
