# Slice 0728: AG dispatch live-provider privacy regression pack

## Intent

Lock down privacy guarantees for the S73 dispatch provider surfaces before
PostgreSQL smoke and later live-provider work.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py`.
- The smoke pack checks provider config, notification request, incident request,
  provider adapter results, HTTP client result, persisted result metadata, and
  AG operations dashboard dispatch projection.
- The regression scans for raw notification payloads, raw external incident
  payloads, raw provider payloads/responses, endpoint paths, provider tokens,
  authorization values, database URLs, idempotency keys, and storage paths.
- Added regression tests in
  `tests/test_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py`.
- Added the privacy smoke to `scripts/quality/run_quality_gate.sh`.

## Boundary

Slice 0728 does not call live provider endpoints. It verifies that the mock HTTP
and provider-readiness surfaces only emit safe hashes, bounded previews, status
codes, counters, redacted endpoint hints, and redaction flags.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py -q --cov=run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression --cov-branch --cov-report=term-missing
```

Result: `6 passed`, `100%` statement coverage, `100%` branch coverage for the
privacy smoke module.

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_privacy_regression.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_live_provider_privacy=pass surfaces=8 values=True keys=True flags=True`.
