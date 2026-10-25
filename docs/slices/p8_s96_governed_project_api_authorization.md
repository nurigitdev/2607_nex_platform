# P8-S96: Governed Project API and OA Authorization

## Status

Completed on 2026-10-25.

## Scope

P8-S96 added the EOS governed Project service and service-token-protected
internal API. It reuses the existing fresh OA authorization source and generic
EOS BusinessOperation/idempotency/outbox coordinator.

The versioned OA scopes are:

```text
project:project:create
project:project:read
project:project:admin
project:membership:manage
```

OA authority and EOS Project membership are independent requirements. OA
scope never substitutes for membership, and membership never substitutes for
current OA authority.

## Governed Boundaries

The API supports:

```text
Project create with one initial OWNER
Project get and bounded list
Project deactivate
membership ADD, REMOVE, and bounded list
```

Every route first admits a service token for the `nex-eos` audience. Every
business action then obtains a fresh OA authorization projection. Membership
management additionally requires an active EOS OWNER or MANAGER; Project
deactivation requires an active OWNER.

Project create and its initial OWNER membership are inserted in the same
transaction as the EOS BusinessOperation, idempotency row, and outbox event.
The other Project mutations use the same transaction coordinator. Canonical
NSL WRITE admission remains assigned to P8-S99.

## READ Filtering

Project and membership reads are tenant-scoped and membership-filtered at the
EOS query boundary. An explicit `project:project:admin` scope may override the
membership filter. Responses are bounded and paginated with deterministic
ordering; IA-side filtering is not trusted.

## Verification

Focused service and route tests:

```text
18 passed
project API coverage             = 100%
governed Project service coverage = 98%
```

Actual `nex_eos_test` PostgreSQL protected smoke:

```text
database identity       = nex_eos_test / nex_eos_user
Project + OWNER replay  = CREATED then REPLAYED
membership ADD/read     = PASS
BusinessOperation rows  = 2
tenant cleanup residue  = 0
result                  = 1 passed / 0 skipped
```

EOS regression:

```text
660 passed
21 expected protected skips
0 failed
```

## Exit Decision

P8-S96 is closed. EOS now owns an atomic, current-authority-checked Project
operation boundary. P8-S97 may add the canonical operation alias registry and
naming enforcement without changing this authorization model.
