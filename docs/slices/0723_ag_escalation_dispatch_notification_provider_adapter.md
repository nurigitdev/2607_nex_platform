# Slice 0723: AG dispatch notification provider contract and mock adapter

## Intent

Add the first live-provider-shaped dispatch adapter for notification, email, and
webhook channels while keeping external network calls disabled.

## Implementation

- Added `build_notification_dispatch_provider_request(...)`, a redaction-safe
  request contract for `NOTIFICATION`, `EMAIL`, and `WEBHOOK` dispatch rows.
- Added `MockNotificationDispatchProvider` and
  `execute_dispatch_with_mock_notification_provider(...)`.
- Request payloads include safe subject/body preview, safe hashes, reason codes,
  provider request hash, idempotency hash, endpoint readiness hints, and bounded
  HTTP timeout/retry settings. They do not include raw notification payloads,
  endpoint paths, service tokens, API keys, or idempotency keys.
- Mock notification execution now returns existing dispatch execution result
  semantics: `SUCCEEDED` for 2xx, `RETRY_WAIT` for retryable HTTP status codes,
  and `FAILED` for non-retryable rejections.
- Added regression coverage for default/fallback profile selection, malformed
  config fallback, redaction, success/retry/failure results, and invalid adapter
  result guardrails.

## Boundary

Slice 0723 does not perform outbound HTTP calls and does not wire the worker
router to notification providers yet. It only establishes the provider request
shape and mock adapter result shape needed by later S73 slices.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `25 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
