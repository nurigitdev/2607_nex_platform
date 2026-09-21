# Slice 0909: CX PostgreSQL re-audit and privacy runbook

## Goal

Compare the canonical CX migration chain with the actual `nex_cx_test`
database and prove that the public schema remains metadata-only.

## Protected execution

The runner is opt-in and refuses any database or role other than
`nex_cx_test` and `nex_cx_user`. It runs all canonical migrations first, reads
PostgreSQL catalogs, and verifies a temporary write/read probe. The probe is
rolled back and its temporary table must no longer exist before the smoke can
pass.

```bash
NEX_CX_CURRENT_STATE_POSTGRES_REAUDIT=1 \
NEX_CX_TEST_DATABASE_URL='<local secret URL>' \
./.venv/bin/python \
  scripts/smoke/run_cx_current_state_postgres_reaudit.py --summary
```

Do not place the URL or password in committed evidence. The runner emits only
its redacted URL, database/role names, schema object names, and counts.

## Privacy failure response

1. Stop CX schema rollout when `public_schema_metadata_only` fails.
2. Record only the reported table/column name; do not query or export values.
3. Confirm whether the column contains private source, chunk, summary, vector,
   prompt, credential, or provider output data.
4. Move private payload ownership behind a dedicated adapter and migrate the
   public schema back to metadata/linkage only.
5. Re-run this protected smoke and the full regression before resuming rollout.

## Observed evidence

- The migration runner connected directly to `nex_cx_test` as `nex_cx_user`.
- All 13 canonical migrations were already present and were safely skipped.
- All 16 core CX tables, declared indexes, and declared constraints were found.
- The longest PostgreSQL identifier was 63 characters, within the 63-byte
  limit.
- No prohibited private-payload column was present in the public schema.
- The temporary insert/select probe succeeded and rollback left zero residue.

This slice creates no persistent table, migration, or smoke row.

## Verification

```bash
./.venv/bin/pytest -q tests/test_cx_current_state_postgres_reaudit.py \
  --cov=nex_cx.postgres_reaudit \
  --cov=run_cx_current_state_postgres_reaudit \
  --cov-branch --cov-report=term-missing
scripts/quality/run_quality_gate.sh -q
```

Observed verification:

```text
focused tests: 18 passed; target statement/branch coverage: 100%
actual PostgreSQL: PASS database=nex_cx_test migrations=13/13
core tables=16 private columns=0 failed checks=0
aggregate regression: 6329 passed, 1 known warning
statement=76229/77110=98.857476332512%
branch=17726/18376=96.46277753591642%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
