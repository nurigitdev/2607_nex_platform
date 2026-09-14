# Slice 0724: AG dispatch external incident provider contract and mock adapter

## Intent

Add the external incident provider request contract and mock adapter for
`INCIDENT` dispatch rows without enabling outbound network calls.

## Implementation

- Added `build_external_incident_dispatch_provider_request(...)`.
- Added `MockExternalIncidentDispatchProvider` and
  `execute_dispatch_with_mock_external_incident_provider(...)`.
- External incident requests store only safe subject/body previews, hashes,
  reason codes, target refs with hashed target id, provider request hash,
  idempotency hash, endpoint readiness hints, and bounded HTTP timeout/retry
  settings.
- Mock incident execution returns `SUCCEEDED` for 2xx and idempotent-conflict
  `409`, `RETRY_WAIT` for retryable status codes, and `FAILED` for
  non-retryable rejections.
- Added regression coverage for redaction, endpoint/token safety,
  unsupported-channel guardrails, success/duplicate/retry/failure outcomes, and
  result contract compatibility.

## Boundary

Slice 0724 does not perform outbound HTTP calls and does not wire the worker
router to external incident providers yet. It prepares the incident adapter
contract for later S73 routing and HTTP client slices.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `28 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
