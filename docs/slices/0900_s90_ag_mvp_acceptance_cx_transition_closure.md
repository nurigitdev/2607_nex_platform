# Slice 0900: S90 AG MVP acceptance and CX transition closure

## Goal

Close the NeX-AG service MVP only when its boundary, policy, 33-requirement
inventory, fail-closed evaluator, protected API, contracts, actual PostgreSQL
proof, privacy runbook, and two-stage CX handoff all agree.

## Closure

- The acceptance scope is the NeX-AG service MVP, not product-wide release or
  production deployment approval.
- Eight blocking gates must pass with fresh server-derived evidence. Missing,
  skipped, stale, future-dated, threshold-failing, wrong-database, or unclean
  evidence remains blocking.
- The actual `nex_ag_test` proof applies current migrations, inserts and selects
  an owned probe, confirms zero-residue cleanup, returns `ACCEPTED`, and verifies
  a `BOUND` AG-to-CX attestation.
- The CX handoff remains two-stage: first verify an immutable `SEALED` candidate,
  then bind its hash to the accepted report ID. Neither stage includes raw
  evidence, credentials, database URLs, or local absolute paths.
- S91 starts from `cx_current_state_reaudit_and_refactoring_checkpoint`; this
  closure does not assume prior CX findings are still current.
- Production release, deployment certification, production identity/external
  notification integration, and distributed load/DR certification remain
  explicit deferred scope.
- No table, index, or migration is introduced.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s90_ag_mvp_acceptance_cx_transition_closure.py \
  --cov=run_s90_ag_mvp_acceptance_cx_transition_closure \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_s90_ag_mvp_acceptance_cx_transition_closure.py \
  --summary

NEX_AG_MVP_ACCEPTANCE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='<protected nex_ag_test URL>' \
NEX_AG_MVP_COVERAGE_JSON='/tmp/nex_platform_0900_coverage.json' \
NEX_AG_MVP_PYTEST_LOG='/tmp/nex_platform_0900_pytest.log' \
./.venv/bin/python \
  scripts/smoke/run_s90_ag_mvp_acceptance_cx_transition_closure.py \
  --summary
```

Observed closure evidence:

```text
focused closure tests: 12 passed, 1 known warning
closure runner statement/branch coverage: 100%
default closure: PASS acceptance=ACCEPTED handoff=BOUND postgres=SKIPPED next=S91
protected closure: PASS acceptance=ACCEPTED handoff=BOUND postgres=PASS next=S91
contract validation: schemas=82 examples=133 negative_fixtures=97 openapi=7
direct SQL: database=nex_ag_test latest_migration=1 probe_residue=0
aggregate regression: 6277 passed, 1 known warning
statement=75617/76498=98.84833590420665%
branch=17654/18304=96.44886363636364%
```
