# Slice 1221: S122 OA identity and membership lifecycle closure

## Closure Decision

S122 closes the durable direct subject and tenant-membership lifecycle boundary.
The implementation now provides revision-guarded state changes, append-only
server-actor events, atomic session revocation, protected APIs, strict wire
contracts, and actual PostgreSQL evidence.

Closed behavior:

- subject states are `ACTIVE`, `DISABLED`, and terminal `DELETED`;
- direct membership states are `ACTIVE` and `DISABLED`;
- mutations require `expected_revision`, a reason for changes, and the
  `identity:lifecycle:write` service scope;
- subject disable/delete and membership disable revoke matching active sessions
  in the same PostgreSQL transaction as the state update and event insert;
- reactivation never restores an old session;
- response contracts reject password, password-hash, token, and undeclared
  private fields;
- the event table remains the short `oa_id_lifecycle_events` identifier.

Explicitly deferred to focused follow-up requirements:

- group registry and group membership lifecycle;
- dedicated bootstrap/admin authorization for compatibility ensure routes;
- credential rotation, rehash, and lockout hardening;
- signed service tokens and JWKS verification.

## PostgreSQL Evidence

The protected Slice 1220 execution used `nex_oa_test` / `nex_oa_user`, applied
`1215_oa_identity_lifecycle`, persisted lifecycle events: `2`, revoked sessions:
`2`, rejected a stale revision, and left cleanup residue across all five tables:
`0`. No DGX or remote model provider was required.

## Quality Cadence

- Slice Gate: Slices 1212-1220
- Checkpoint Gate: Slice 1216
- Full Gate: Slice 1221

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s122_oa_identity_membership_lifecycle_closure.py \
  --summary

./scripts/quality/run_quality_gate.sh
```

Observed evidence:

- protected Slice 1220 PostgreSQL smoke: `1 passed, 18 deselected`;
- S122 closure: `PASS`, evidence `9/9`, components `5/5`, protected
  operations `2`, PostgreSQL events `2`;
- Full Gate Python regression: `9911 passed, 12 skipped`;
- statement coverage: `98.58%` (threshold `95%`);
- branch coverage: `97.03%` (threshold `85%`);
- contract validation: `132` schemas, `190` positive examples, `160`
  negative examples, and `7` OpenAPI documents;
- AE Web regression: `293 passed`;
- Full Gate exit status: `0`.
