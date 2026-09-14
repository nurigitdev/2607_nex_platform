# Slice 0736: AG dispatch incident loopback smoke

## Intent

Prove the live HTTP external incident dispatch path against a local loopback HTTP
server before any real incident endpoint exists.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_incident_loopback_smoke.py`.
- The smoke is protected by
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_INCIDENT_LOOPBACK_SMOKE=1`.
- The script starts a `127.0.0.1` HTTP server, sends one external incident
  dispatch through `UrllibDispatchProviderHttpTransport`, and verifies that the
  loopback server received a redacted live HTTP envelope.
- Evidence records request counts, hashes, safe status, response hash, and target
  id hash confirmation only. The bearer token, raw target id, and raw endpoint
  path are intentionally withheld.
- Added a skip-safe quality gate hook.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_incident_loopback_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_incident_loopback_smoke --cov-branch --cov-report=term-missing
```

Result: `5 passed`, `100%` statement coverage, `100%` branch coverage for the
incident loopback smoke script.

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_INCIDENT_LOOPBACK_SMOKE=1 ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_incident_loopback_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_incident_loopback_smoke=pass transport=local_loopback_http_server requests=1 status_code=201`.
