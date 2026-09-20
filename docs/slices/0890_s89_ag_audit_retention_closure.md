# Slice 0890: S89 AG audit retention closure

## Goal

Close S89 only after its boundary, runtime lifecycle, contracts, actual
PostgreSQL evidence, privacy controls, and operator runbook agree.

## Closure

- Retention policy is bounded and dry-run-first. Physical purge requires an
  explicitly enabled external archive provider and explicit confirmation.
- `service_operational_events` and `ag_ev_exports` remain source tables;
  `ag_ret_archives` stores only sealed receipts and purge tombstones.
- Runtime evidence covers candidate selection, recoverable receipt sealing,
  eligible dry-run, transactional purge, and idempotent retry without exposing
  source payloads or archive object references.
- Strict JSON Schema and OpenAPI, privacy negative fixtures, two deterministic
  candidate indexes, and the protected operations routes are present.
- The actual `nex_ag_test` lifecycle proves two source-kind purges, index use,
  persisted tombstones, and zero-residue cleanup.
- Production object storage selection, cross-service retention orchestration,
  and legal-hold case management remain explicit deferred scope.
- S90 retains AG MVP acceptance and the CX transition checkpoint.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s89_ag_audit_retention_closure.py \
  --cov=run_s89_ag_audit_retention_closure \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_s89_ag_audit_retention_closure.py --summary

NEX_AG_AUDIT_RETENTION_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='<protected nex_ag_test URL>' \
./.venv/bin/python \
  scripts/smoke/run_s89_ag_audit_retention_closure.py --summary
```

Observed closure evidence:

```text
focused closure tests: 10 passed, 1 known warning
closure runner statement/branch: 100%
s89_ag_audit_retention_closure=pass slice_range=0881-0890 contracts=PASS postgres=SKIPPED privacy=PASS
s89_ag_audit_retention_closure=pass slice_range=0881-0890 contracts=PASS postgres=PASS privacy=PASS
contract validation: schemas=81 examples=132 negative_fixtures=95 openapi=7
direct SQL: database=nex_ag_test migrations_0884_0887=true indexes=3
direct SQL: event_residue=0 export_residue=0 receipt_residue=0
aggregate regression: 6159 passed, 1 known warning
statement=74810/75691=98.836057127003%
branch=17484/18134=96.415572956877%
```
