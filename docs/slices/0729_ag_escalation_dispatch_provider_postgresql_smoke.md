# Slice 0729: AG dispatch provider PostgreSQL smoke evidence

## Intent

Prove that S73 provider-routed dispatch execution works against the real
`nex_ag_test` PostgreSQL database and persists safe provider diagnostics.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py`.
- The smoke migrates `nex_ag_test`, seeds one case, one escalation, and two AG
  dispatch outbox rows: one `EMAIL` notification dispatch and one `INCIDENT`
  external incident dispatch.
- The worker runs with `provider_mode=mock_http`, processes both rows through
  the provider router, persists safe execution metadata, verifies AG operations
  dashboard provider diagnostics, directly observes PostgreSQL rows, and cleans
  up smoke data.
- Added regression tests in
  `tests/test_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py`.
- Added the protected smoke to `scripts/quality/run_quality_gate.sh`.

## Boundary

Slice 0729 uses the real test database but still does not call live provider
endpoints. Provider delivery remains mock HTTP until a later protected live
transport decision explicitly enables outbound calls.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_provider_postgres_smoke --cov-branch --cov-report=term-missing
```

Result: `10 passed`, `100%` statement coverage, `100%` branch coverage for the
provider PostgreSQL smoke module.

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_PROVIDER_POSTGRES_SMOKE=1 NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test' PYTHONPATH=services/_shared:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_provider_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_provider_postgres_smoke=pass dispatches=2 succeeded=2 metadata=2 deleted_dispatches=2`.
