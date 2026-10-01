# Slice 1210: OA current-state PostgreSQL re-audit

## Goal

Apply the current OA migration chain to the actual `nex_oa_test` database and
prove catalog state, credential-backed login, session lifecycle, privacy, and
complete smoke-row cleanup.

## Protected Boundary

- Execution requires `NEX_OA_CURRENT_STATE_POSTGRES_REAUDIT=1`.
- The runner only accepts the `nex_oa_user@nex_oa_test` target.
- Migration, catalog, workflow, and cleanup evidence contains no database
  password, raw login password, password hash, token, or unredacted URL.
- DGX providers are outside the OA identity boundary and are not required.

## Actual Verification

The protected runner connected to the actual local PostgreSQL test database.

- Database/role: `nex_oa_test` / `nex_oa_user`.
- Migrations: `11/11`; all were already recorded and no migration was missing.
- Catalog: 5 core OA tables, 34 declared indexes, and 11 declared constraints
  were present; the longest actual identifier was 63 bytes.
- Workflow: all 22 checks passed across credential ensure, membership ensure,
  employee/password login, session readback, active introspection, revocation,
  and revoked introspection.
- Persistence: credential, membership, and session counts were each 1 during
  the probe; the session state was `REVOKED`.
- Privacy: raw-password matches and forbidden private columns were both 0.
- Cleanup: one session, credential, membership, subject, and tenant were deleted;
  post-cleanup residue counts for all five were 0.

## Commands

```bash
NEX_OA_CURRENT_STATE_POSTGRES_REAUDIT=1 \
NEX_OA_TEST_DATABASE_URL='<test-database-url>' \
./.venv/bin/python \
  scripts/smoke/run_oa_current_state_postgres_reaudit.py --summary

./.venv/bin/pytest -q tests/test_oa_current_state_postgres_reaudit.py \
  --cov=nex_oa.postgres_reaudit \
  --cov=run_oa_current_state_postgres_reaudit \
  --cov-branch --cov-report=term-missing

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_current_state_postgres_reaudit.py \
  --coverage-target services/nex-oa/nex_oa/postgres_reaudit.py \
  --coverage-target scripts/smoke/run_oa_current_state_postgres_reaudit.py \
  --smoke scripts/smoke/run_oa_current_state_postgres_reaudit.py
```

The default quality gate invokes the protected runner without activation and
therefore records `SKIPPED`; the explicit command above is the actual database
evidence for this Slice.
