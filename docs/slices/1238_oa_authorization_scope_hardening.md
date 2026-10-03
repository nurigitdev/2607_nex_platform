# Slice 1238: OA bootstrap and privileged-scope hardening

## Result

- Subject and membership compatibility `ensure` routes now require both
  `service:call` and the dedicated `identity:bootstrap:write` scope.
- Subject and membership read routes remain compatible with `service:call`.
- Missing or invalid claims return `401`; valid claims missing the dedicated
  scope return `403` with `TOKEN_SCOPE_MISSING`.
- `identity:bootstrap:write`, `authorization:admin`, and
  `authorization:read` are independent grants. None implies another.
- Existing protected PostgreSQL smoke clients that create test identities now
  request the bootstrap scope explicitly.
- No persistence schema or database table changed in this Slice.

## Authorization Matrix

| Operation | Required scopes |
| --- | --- |
| Ensure subject or membership | `service:call`, `identity:bootstrap:write` |
| Read subject or membership | `service:call` |
| Mutate role/group authorization | `service:call`, `authorization:admin` |
| Read effective grants/events | `service:call`, `authorization:read` |

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_subjects.py \
  --test tests/test_nex_oa_memberships.py \
  --test tests/test_oa_authorization_scope_hardening.py \
  --coverage-target services/nex-oa/nex_oa/identity_access.py \
  --coverage-target scripts/smoke/run_oa_authorization_scope_hardening.py \
  --smoke scripts/smoke/run_oa_authorization_scope_hardening.py
```

Observed result:

- OA regression: `383 passed, 2 skipped`
- Statement coverage: `98.57%` (required `95%`)
- Branch coverage: `96.70%` (required `94%`)
- Identity access policy: `100%` statement / `100%` branch
- Protected smoke runner: `100%` statement / `100%` branch
- Contract validation: `134` schemas, `192` examples, `162` negative
  examples, and `7` OpenAPI documents
- Scope separation smoke: `11/11` checks across `3` dedicated scopes
- Slice Gate: `5/5` commands passed
