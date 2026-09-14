# Slice 0735: AG dispatch notification loopback smoke

## Intent

Prove the live HTTP notification dispatch path against a local loopback HTTP
server before any real external notification endpoint exists.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py`.
- The smoke is protected by
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_NOTIFICATION_LOOPBACK_SMOKE=1`.
- The script starts a `127.0.0.1` HTTP server, sends one notification dispatch
  through `UrllibDispatchProviderHttpTransport`, and verifies that the loopback
  server received a redacted live HTTP envelope.
- Evidence records request counts, hashes, safe status, and response hash only.
  The bearer token and raw endpoint path are intentionally withheld.
- Added a skip-safe quality gate hook.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_notification_loopback_smoke --cov-branch --cov-report=term-missing
```

Result: `5 passed`, `100%` statement coverage, `100%` branch coverage for the
notification loopback smoke script.

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_NOTIFICATION_LOOPBACK_SMOKE=1 ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_notification_loopback_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_notification_loopback_smoke=pass transport=local_loopback_http_server requests=1 status_code=202`.
