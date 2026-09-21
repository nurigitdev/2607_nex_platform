# Slice 0919: CX Private Ownership PostgreSQL Smoke Evidence

## Goal

Verify the S92 ownership and private-metadata persistence controls against the
actual `nex_cx_test` PostgreSQL database, not an in-memory or SQLite substitute.

## Protected execution

The runner accepts only the `test` profile and the exact
`nex_cx_user@.../nex_cx_test` target. It applies the current NeX-CX migration
chain before writing evidence rows. DGX Spark is not used because no embedding,
reranking, or generation provider is invoked.

```bash
NEX_CX_PRIVATE_OWNERSHIP_POSTGRES_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test' \
./.venv/bin/python scripts/smoke/run_cx_private_ownership_postgres_smoke.py --summary
```

## Evidence scope

- Confirms the actual database and role plus the Slice 0917 migration ledger.
- Commits two distinct owner scopes and verifies content, job, processing,
  retrieval, generation, and remediation owner lineage.
- Confirms retrieval evidence cannot mix owner scopes.
- Confirms owner-scoped selects do not return another owner's records.
- Confirms generation persistence rejects prompt-bearing private metadata and
  has no private payload columns.
- Deletes all smoke rows and verifies cleanup from a fresh connection.

The default quality gate executes the runner in `SKIPPED` mode. Actual
PostgreSQL evidence requires the explicit opt-in shown above.

## Recorded evidence

On 2026-09-21 the protected runner connected as
`nex_cx_user@nex_cx_test`, applied migration
`0917_cx_owner_lineage_persistence`, committed and re-read 16 smoke rows across
two owner scopes, passed all 17 checks, and verified zero remaining smoke rows
from a fresh connection. The redacted summary was:

```text
cx_private_ownership_postgres_smoke=pass database=nex_cx_test rows=16 owners=2 failed_checks=0 dgx_required=False
```
