# Slice 0898: AG MVP acceptance PostgreSQL smoke

## Goal

Prove the NeX-AG service MVP acceptance and AG-to-CX transition against the
actual `nex_ag_test` PostgreSQL database, while removing the circular dependency
between acceptance and handoff creation.

## Two-stage handoff

1. Build and independently verify a deterministic `SEALED` CX handoff candidate.
2. Evaluate all eight blocking gates, including the sealed-candidate gate and
   confirmed PostgreSQL cleanup.
3. Only after an `ACCEPTED`/`READY_FOR_CX` report exists, produce a separate
   `BOUND` attestation over the candidate manifest hash and acceptance ID.

The candidate remains immutable and acceptance-independent. The attestation is
also hash-verifiable and cannot be rebound to another candidate or report.

## PostgreSQL evidence

- The protected runner requires explicit opt-in, an actual test database URL,
  and fresh pytest plus coverage artifacts produced within 24 hours.
- It applies current NeX-AG migrations, inserts a uniquely owned operational
  event, directly selects `current_database()`, the latest migration, and the
  probe row from PostgreSQL.
- The probe is deleted and zero residue is confirmed before the PostgreSQL gate
  is marked `PASS` or the acceptance API is called.
- The final response must be `ACCEPTED`, all eight gates must pass, and the
  handoff attestation must verify as `BOUND`.
- Raw event text, details, database URL, and credentials are excluded from
  emitted evidence. The default quality-gate invocation remains safely skipped
  until explicitly enabled.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_cx_transition_handoff.py \
  tests/test_ag_mvp_acceptance_postgres_smoke.py \
  --cov=nex_ag.cx_transition_handoff \
  --cov=run_ag_mvp_acceptance_postgres_smoke \
  --cov-branch --cov-report=term-missing

NEX_AG_MVP_ACCEPTANCE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='<protected nex_ag_test URL>' \
NEX_AG_MVP_COVERAGE_JSON='/tmp/nex_platform_0898_coverage.json' \
NEX_AG_MVP_PYTEST_LOG='/tmp/nex_platform_0898_pytest.log' \
./.venv/bin/python \
  scripts/smoke/run_ag_mvp_acceptance_postgres_smoke.py --summary
```

Observed verification:

```text
focused handoff/smoke tests: 37 passed, 1 known warning
focused handoff/smoke statement and branch coverage: 100%
aggregate regression: 6256 passed, 1 known warning
statement=75383/76264=98.84480226581348%
branch=17634/18284=96.44497921680157%
live smoke: PASS
database=nex_ag_test acceptance=ACCEPTED handoff=BOUND remaining=0
direct SQL: database=nex_ag_test latest_migration=1 probe_residue=0
```
