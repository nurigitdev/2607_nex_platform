# Slice 1180: MO Catalog Lifecycle PostgreSQL Smoke

## Scope

This protected smoke targets only `nex_mo_user@nex_mo_test`. It rejects other
profiles, roles, database names, and missing explicit activation.

The exercise performs the following operations against actual PostgreSQL:

1. apply or verify all NeX-MO migrations;
2. verify `mo_model_catalog` and `mo_alias_bindings` exist;
3. create and activate two unique generation candidates;
4. activate candidate A on a unique alias and atomically replace it with B;
5. dispose the first engine and recover state through a fresh engine/session;
6. resolve the active alias through the runtime route source;
7. reject a stale expected revision and append a rollback binding to A;
8. read the history through the authenticated API and verify redaction;
9. delete only smoke-owned bindings and catalog entries and prove zero residue.

## Protected command

```bash
NEX_MO_CATALOG_POSTGRES_SMOKE=1 \
NEX_MO_CATALOG_POSTGRES_SMOKE_PROFILE=test \
NEX_MO_TEST_DATABASE_URL='postgresql+psycopg://nex_mo_user:***@127.0.0.1:5432/nex_mo_test' \
./.venv/bin/pytest -q \
  tests/test_mo_catalog_lifecycle_postgres_smoke.py::test_protected_catalog_postgres_smoke_uses_actual_nex_mo_test
```

Evidence must report the real database identity, current migration count, two
catalog rows, three append-only binding rows, restart recovery, stale revision
rejection, rollback restoration, authenticated API behavior, redaction, and
zero cleanup residue. Passwords and the unredacted database URL are never
included in evidence.

## Executed evidence

Executed on 2026-10-01 against `nex_mo_user@nex_mo_test`:

- protected pytest: `1 passed`;
- checks: `13/13`;
- migrations: `0 applied + 9 current / 9 planned`;
- lifecycle mutations: `7`;
- targeted cleanup residue: `0`.
