# Slice 1230: OA credential security PostgreSQL smoke evidence

## Goal

Prove the S123 credential and session security path against the actual
`nex_oa_test` database. The protected workflow covers migration currency,
atomic login lockout, adaptive hash upgrade, session lifecycle, credential
rotation, authentication-event persistence, privacy, and cleanup.

## Protected Execution

The runner accepts only `nex_oa_user@.../nex_oa_test`, requires explicit
opt-in, and redacts the database password from evidence.

```bash
NEX_OA_CREDENTIAL_SECURITY_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:<password>@127.0.0.1:5432/nex_oa_test' \
./.venv/bin/python scripts/smoke/run_oa_credential_security_postgres_smoke.py --summary
```

## Evidence

The 2026-10-01 protected execution completed with:

- database/role: `nex_oa_test` / `nex_oa_user`
- migration plan: `13`; newly applied: `1225_oa_credential_session_security`
- failed login path: five generic `401` responses, persisted failure count `5`,
  and atomic `LOCKED` transition on the fifth attempt
- timed recovery: an expired lock admitted the correct password, reset the
  failure state, and upgraded the legacy PBKDF2 hash to `argon2id.v1`
- session lifecycle: two distinct random handles, sliding idle lease touch,
  and two credential-rotation revocations with zero active sessions remaining
- auth events: `12` total, exactly six `SUCCEEDED` and six `BLOCKED`; event
  projections contain no password, hash, or session identifier
- cleanup: events `12`, sessions `2`, credential `1`, membership `1`, subject
  `1`, tenant `1`; residue across all six tables: `0`
- protected pytest: `1 passed`, `0 skipped`

The protected test remains skipped during ordinary regression unless the opt-in
flag is enabled, so normal Slice and Full Gates do not mutate PostgreSQL.

## Verification

```bash
./.venv/bin/pytest -q tests/test_oa_credential_security_postgres_smoke.py

NEX_OA_CREDENTIAL_SECURITY_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:<password>@127.0.0.1:5432/nex_oa_test' \
./.venv/bin/pytest -q tests/test_oa_credential_security_postgres_smoke.py \
  -k protected_actual

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_credential_security_postgres_smoke.py \
  --coverage-target services/nex-oa/nex_oa/credential_security_postgres_smoke.py \
  --smoke scripts/smoke/run_oa_credential_security_postgres_smoke.py
```

Observed Slice Gate result: `319 passed, 2 protected skips`; overall statement
`98.25%`, overall branch `96.08%`, smoke evaluator statement/branch `100%`,
contract inventory `134/192/162`, and commands `5/5` passed.
