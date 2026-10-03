# Slice 1241: S124 OA group and role authorization closure

## Closure Decision

S124 closes the OA tenant-scoped group and role authorization baseline. The
implementation now provides revision-guarded role, group, membership, and
assignment lifecycle management; allow-only effective grant composition;
authorization-aware session issuance and invalidation; protected management
and read APIs; strict contracts; privacy-safe events; and actual PostgreSQL
evidence.

Closed behavior:

- roles, groups, group members, and group-role assignments are tenant scoped;
- direct membership grants and active group-role grants compose by set union;
- unknown roles, stale revisions, inactive records, and cross-tenant access
  fail closed;
- authorization changes append privacy-safe events and revoke affected active
  sessions in the same transaction;
- compatibility bootstrap writes, authorization administration, and reads use
  independent scopes;
- six canonical schemas and eight protected OpenAPI operations match runtime
  responses;
- short PostgreSQL table names remain within the frozen identifier boundary.
- S121-S123 closure checks accept only monotonic reductions in lifecycle and
  contract gaps while continuing to reject drift above their original limits.

Explicitly deferred to focused follow-up requirements:

- explicit deny rules;
- nested groups;
- signed service tokens and JWKS verification.

## PostgreSQL Evidence

The protected Slice 1240 execution used `nex_oa_test` / `nex_oa_user`, applied
`1234_oa_group_role_authorization`, exercised ten protected workflow checks,
persisted five privacy-safe authorization events, revoked two active sessions,
verified restart readback, and left cleanup residue across all nine table
categories at zero. DGX and remote model providers were not required.

## Quality Cadence

- Slice Gate: Slices 1232-1240
- Checkpoint Gate: Slice 1236
- Full Gate: Slice 1241

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s124_oa_group_role_authorization_closure.py \
  --summary

NEX_OA_AUTHORIZATION_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_quality_gate.sh
```

Observed evidence:

- S124 closure: `PASS`, evidence `9/9`, components `5/5`, protected
  operations `8`, PostgreSQL events `5`;
- actual PostgreSQL smoke: `PASS` on `nex_oa_test`, revoked sessions `2`,
  cleanup residue `0`;
- Python regression: `10,091 passed`, `13 skipped`, `123 warnings`;
- statement coverage: `98.52%`;
- branch coverage: `97.04%` with the enforced `94%` minimum;
- contract validation: `140` schemas, `198` positive examples, `168`
  negative examples, and `7` OpenAPI documents;
- Full Gate exit status: `0`.
