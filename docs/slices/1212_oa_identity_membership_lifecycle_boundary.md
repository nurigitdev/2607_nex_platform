# Slice 1212: OA identity and membership lifecycle boundary

## Goal

Start S122 by freezing the durable direct-identity lifecycle boundary before
adding mutation routes or changing persisted OA records.

## Decision

- NeX-OA owns subject, direct tenant membership, and user-session lifecycle.
- Existing states remain canonical: subjects use `ACTIVE`, `DISABLED`, and
  terminal `DELETED`; memberships use `ACTIVE` and `DISABLED`.
- State changes require an expected revision. A stale writer fails closed and
  cannot overwrite a newer lifecycle decision.
- Disabling or deleting a subject, or disabling a membership, revokes matching
  active sessions in the same durable transaction.
- New lifecycle mutation routes require `identity:lifecycle:write`.
- Existing ensure routes retain their current service-call compatibility;
  bootstrap authorization tightening is handled separately from lifecycle
  mutations to avoid silently breaking login orchestration.
- An append-only, privacy-safe lifecycle event table is required. Table and
  constraint names must remain within PostgreSQL identifier limits.
- Group registry and group membership remain deferred. S122 hardens direct
  subject-to-tenant membership only.
- Actual `nex_oa_test` PostgreSQL evidence is mandatory. DGX providers are not
  part of this requirement.

## Slice Plan

Slices 1212 through 1221 cover boundary, subject and membership transition
domains, durable repository and migration, protected APIs, revocation cascade,
contracts/privacy, PostgreSQL evidence, and closure.

The tiered quality cadence remains Slice Gate on every Slice, Checkpoint Gate
at Slice 1216, and Full Gate at Slice 1221.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_oa_identity_membership_lifecycle_boundary.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_identity_membership_lifecycle_boundary.py \
  --coverage-target scripts/smoke/run_oa_identity_membership_lifecycle_boundary.py \
  --smoke scripts/smoke/run_oa_identity_membership_lifecycle_boundary.py
```
