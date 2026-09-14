# Slice 0730: S73 operator review escalation dispatch provider closure

## Intent

Close S73 by verifying the AG dispatch provider readiness work from Slice 0721
through Slice 0729.

## Implementation

- Added
  `scripts/smoke/run_s73_operator_review_escalation_dispatch_provider_closure.py`.
- The closure verifies required S73 files, docs, tests, quality-gate hooks,
  provider config/request/result schemas, mock adapters, HTTP client foundation,
  worker provider router, provider diagnostics dashboard, privacy regression,
  and protected PostgreSQL smoke evidence.
- Added regression tests in
  `tests/test_s73_operator_review_escalation_dispatch_provider_closure.py`.
- Added the closure smoke to `scripts/quality/run_quality_gate.sh`.

## Boundary

S73 closes provider readiness for mock HTTP routing and diagnostics. Live
network delivery remains deferred until a later protected transport slice
explicitly enables outbound provider calls.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_s73_operator_review_escalation_dispatch_provider_closure.py -q --cov=run_s73_operator_review_escalation_dispatch_provider_closure --cov-branch --cov-report=term-missing
```

Result: `6 passed`, `100%` statement coverage, `100%` branch coverage for the
S73 closure module.

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/python scripts/smoke/run_s73_operator_review_escalation_dispatch_provider_closure.py --summary
```

Result:
`s73_operator_review_escalation_dispatch_provider_closure=pass slice_range=0721-0730 required_files=27 boundary=ag_owned_operator_review_escalation_dispatch_provider_readiness table=ag_op_esc_dispatches modes=mock_first_only,mock_http,guarded_live_http privacy=provider_surfaces_redacted smoke=test_db_protected_provider_router`.
