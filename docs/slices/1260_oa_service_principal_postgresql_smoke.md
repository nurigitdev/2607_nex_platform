# Slice 1260: OA Service Principal PostgreSQL Smoke Evidence

## Goal

Verify the S126 principal and client-credential lifecycle against the actual
`nex_oa_test` PostgreSQL database, including migration currency, protected API
access, restart-safe reads, secret hashing, and cleanup.

## Protected workflow

- The runner requires explicit opt-in and rejects any database role/name other
  than the dedicated OA test target.
- All 15 OA SQL migrations are applied or confirmed current before execution.
- A unique service principal is created through the protected API.
- Two credentials are issued through a rotation, verified during the grace
  window, read back through a fresh repository, and one is revoked.
- SQL evidence confirms two Argon2id hashes and zero plaintext secret matches.
- Created credential and principal rows are deleted, with zero residue verified.
- Reports contain only counts and boolean checks; raw secrets and hashes are not
  serialized as evidence.

## Run

```bash
NEX_OA_SERVICE_PRINCIPAL_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='<OA test database URL>' \
./.venv/bin/python scripts/smoke/run_oa_service_principal_postgres_smoke.py --summary
```
