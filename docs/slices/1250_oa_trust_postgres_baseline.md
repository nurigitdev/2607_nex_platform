# Slice 1250: OA production-trust PostgreSQL baseline smoke

## Goal

Prove the S125 baseline against the actual `nex_oa_test` PostgreSQL database,
including current migrations, opaque sessions, privacy, and cleanup.

## Evidence

- The protected runner accepts only `nex_oa_user@.../nex_oa_test`, executes all
  OA migrations, verifies the complete migration ledger, and confirms the
  server identifies itself as PostgreSQL.
- A synthetic membership and opaque user session are issued through the OA
  API, read, introspected active, revoked, introspected inactive, checked in
  PostgreSQL, and deleted. A second database query proves zero residue.
- Public schema inspection rejects raw token, private key, password, API key,
  and credential-secret columns. It also proves the four S126 trust tables do
  not yet exist.
- Current mock service-token compatibility is issued and validated only in
  memory. Evidence contains a short SHA-256 fingerprint, never the token.
- No DGX or model provider is required for OA trust baseline evidence.

## Verification

```bash
NEX_OA_TRUST_BASELINE_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./.venv/bin/pytest -q tests/test_oa_trust_postgres_baseline.py
```

The password is supplied only through the local environment and is redacted
from committed evidence and output.

## Observed Evidence

- Database/role: `nex_oa_test` / `nex_oa_user`
- PostgreSQL migration ledger: `14/14`
- Cleanup residue: `0`
- Protected test: `25 passed`, no skip
- Slice Gate: `549 passed, 3 skipped`
- Statement coverage: `98.88%`
- Branch coverage: `97.95%` with the enforced `94%` minimum
- Slice 1250 modules: statement `100%`, branch `100%`
