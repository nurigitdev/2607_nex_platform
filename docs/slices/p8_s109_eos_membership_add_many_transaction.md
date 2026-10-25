# P8-S109: EOS Membership ADD_MANY Transaction

## Scope

P8-S109 implements `PROJECT.MEMBERSHIP.ADD_MANY` as one EOS
BusinessOperation, one database transaction, and one outbox event. It reuses
`eos_project_member`, `eos_business_operation`, `eos_idempotency`, and
`eos_outbox`; no table or migration is added.

The protected endpoint is:

```text
POST /internal/v1/projects/{project_id}/memberships:add-many
```

The requester is checked against fresh OA authority before execution and is
checked again as an active Project OWNER or MANAGER while the Project row is
locked. Target subjects are freshly checked through OA immediately before the
transaction. OA unavailability or malformed authority remains an operation
failure and cannot be converted into partial success.

## Transaction Semantics

The existing Project-row lock is acquired before subject rows. Canonical
subjects are processed in UTF-8 byte order, which serializes batch-versus-batch
and single-ADD-versus-batch mutations for the same Project. Membership IDs use
the existing AE single-ADD UUIDv5 namespace, so both paths converge on the same
relationship identity.

Committed item outcomes are:

- `ADDED`
- `REACTIVATED`
- `ALREADY_ACTIVE`
- `SUBJECT_INACTIVE`
- `NOT_ELIGIBLE`
- `ROLE_CONFLICT`

Expected item failures do not roll back successful items. Persistence,
authorization-source, tamper, and unexpected constraint failures remain
fail-closed transaction failures. Exact idempotent replay returns the original
aggregate and item projection without another mutation.

CA05 leaves no top-level state for the case where candidates passed AE
admission but every item is rejected by fresh commit-time checks. S109 closes
that narrow state gap as `REJECTED` with a durable `COMMITTED`
BusinessOperation and zero membership mutations. Pre-admission `REJECTED`
continues to create no BusinessOperation.

## Hash Boundary

The S108 approval binds the canonical governed payload without transport or
BusinessOperation envelope fields. `project_membership_add_many_payload_hash`
validates that exact NSL-compatible hash at EOS. Existing single Project
operation hashing remains unchanged. A contract vector proves the S108
admission hash and S109 EOS hash are identical.

## Contracts

P8-S109 adds strict command and result schemas plus positive examples. The
operation registry advances to `p8-s109.v1` and admits the canonical
three-segment operation name.

Contract validation passed with `205` schemas, `269` positive examples, `229`
negative examples, and `9` OpenAPI documents.

## Verification

- focused unit, route, contract, and replay suite: `73 passed`
- protected actual PostgreSQL concurrency smoke: `1 passed`
- verified database/user: `nex_eos_test` / `nex_eos_user`
- concurrent batch versus batch: one `ADDED`, one `ALREADY_ACTIVE`, one row
- concurrent single ADD versus ADD_MANY: one relationship row
- tenant-scoped PostgreSQL residue after cleanup: `0`
- EOS Slice Gate: `696 passed`, `21` expected protected-profile skips
- EOS statement coverage: `98.36%`
- EOS branch coverage: `96.78%`
- Slice Gate commands: `3/3`, `35.741` seconds
- contract validation and `git diff --check`: passed

The Slice Gate coverage report is
`reports/quality/p8-s109-eos.coverage.json`.

## Exit

P8-S109 is complete. P8-S110 may expose the same canonical collection as one
NSL v0.2.1 controlled WRITE node while preserving the approved payload hash,
BusinessOperation identity, and item-result projection.
