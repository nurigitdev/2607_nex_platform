# Slice 0734: AG dispatch live HTTP adapter

## Intent

Map live HTTP transport client results into AG escalation dispatch execution
results without wiring external network delivery into the worker yet.

## Implementation

- Added `execute_dispatch_with_live_http_transport`.
- The adapter builds the existing notification or external incident provider
  request, executes it through an injected transport, and converts the HTTP
  client result into the dispatch execution result contract.
- Execution results now preserve safe HTTP diagnostics such as status code,
  response body hash, and attempt count while continuing to reject raw payloads,
  endpoint URLs, headers, and tokens in evidence.
- Unsupported live channel types fail before transport execution.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `37 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
