# Slice 0252: OA Local Credential Registry Foundation

## Scope

Add the OA-owned local credential registry needed for company employee id plus
password login. This slice stores credential records and hash verification
helpers, but does not expose the public user login API yet.

## Implemented

- Added `oa_local_credentials` to the `nex-oa` migration set.
- Added `nex_oa.credentials` with:
  - in-memory credential registry
  - SQLAlchemy credential registry
  - service-runtime registry factory
  - protected internal credential ensure/read routes
  - password hash and verification helpers
- Added protected endpoints:
  - `POST /internal/v1/auth/local-credentials/ensure`
  - `GET /internal/v1/auth/local-credentials/tenants/{tenant_id}/employee-ids/{employee_id}`
- Registered the credential registry in the `nex-oa` app using the same subject
  registry runtime as membership/session code.
- Added regression coverage for hash verification, validation failures,
  service-claim auth, SQLite persistence, migration shape, and app entrypoint
  registration.

## Security Boundary

- Raw passwords are accepted only by the protected OA credential seed path and
  are immediately hashed.
- Raw passwords are never stored.
- API/snapshot responses never include password hashes or `password_hash`
  column names.
- Credential metadata rejects password, token, cookie, authorization, and secret
  shaped fields.
- Employee id is normalized as a tenant-scoped lookup alias.
- Subject refs remain stable `oa.user` refs; if `subject_id` is omitted for MVP
  local seeding, OA defaults it to the normalized employee id.

## Hash Policy

The current local implementation uses `pbkdf2_sha256.v1` with standard-library
PBKDF2-HMAC-SHA256 because the repository does not yet include Argon2/passlib
dependencies. Slice 0251 still records `argon2id` as the recommended production
target. The credential record stores the algorithm id so the hash policy can be
upgraded later without changing downstream AE/CX subject contracts.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_oa_credentials.py tests/test_database_schema_foundation.py -q`
  - Result: `38 passed, 1 warning`
- Credential module coverage:
  `./.venv/bin/pytest tests/test_nex_oa_credentials.py --cov=nex_oa.credentials --cov-branch --cov-report=term-missing -q`
  - Result: `20 passed, 1 warning`; `nex_oa.credentials` at 100% statement and branch coverage.
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1796 passed, 1 warning`
  - Statement coverage: `98.18%`
  - Branch coverage: `94.43%`
