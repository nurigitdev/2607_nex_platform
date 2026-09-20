# Slice 0888: AG audit retention PostgreSQL smoke

## Goal

Prove the S89 archive-receipt and guarded-purge lifecycle against the actual
`nex_ag_test` PostgreSQL database without treating a skipped run as evidence.

## Implementation

- Added an opt-in smoke runner that applies every NeX-AG test migration before
  opening SQLAlchemy stores against PostgreSQL.
- Seeds one old operational event and one old redacted evidence export, reads
  both through the production retention-candidate query, and builds recoverable
  external archive receipts from the exact source hashes.
- Exercises the protected operations API for projection, dry-run eligibility,
  explicit confirmed purge, and idempotent retry for both source kinds.
- Verifies physical source deletion, persisted `PURGED` tombstones, migration
  presence, both Slice 0887 indexes, and PostgreSQL planner usability.
- Deletes only smoke-owned receipts and any remaining sources, then requires
  zero residue. Response evidence excludes raw payloads, object references,
  database credentials, and confirmation values.
- Registered the non-opt-in runner in the quality gate; it reports `SKIPPED`
  unless the protected environment flag is explicitly enabled.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_ag_audit_retention_postgres_smoke.py \
  --cov=run_ag_audit_retention_postgres_smoke \
  --cov-branch --cov-report=term-missing

NEX_AG_AUDIT_RETENTION_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='<protected nex_ag_test URL>' \
./.venv/bin/python \
  scripts/smoke/run_ag_audit_retention_postgres_smoke.py --summary
```

Observed verification:

```text
focused smoke runner tests: 14 passed, 1 known warning
smoke runner statement/branch: 100%
live smoke: PASS
database=nex_ag_test backend=postgresql candidates=2 purged=2 indexes=2 cleaned=True
direct SQL: migration_present=true indexes=2 event_residue=0 export_residue=0 receipt_residue=0
aggregate regression: 6141 passed, 1 known warning
statement=74563/75444=98.832246434441%
branch=17466/18116=96.412011481563%
```
