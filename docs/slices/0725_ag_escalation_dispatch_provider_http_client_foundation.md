# Slice 0725: AG dispatch provider HTTP client foundation

## Intent

Add a redaction-aware HTTP client execution foundation for dispatch providers
without opening live network access.

## Implementation

- Added `MockDispatchProviderHttpTransport`, an injected transport used for
  deterministic HTTP-shaped tests.
- Added `execute_dispatch_provider_http_request(...)`, which applies bounded
  timeout/retry settings, classifies success/retryable/rejected HTTP statuses,
  handles transport timeouts, and returns a safe HTTP client result contract.
- Added `DISPATCH_PROVIDER_HTTP_CLIENT_RESULT_SCHEMA_VERSION`.
- HTTP client results include provider request schema/profile/type refs, attempt
  counts, timeout settings, status code, response body hash, result hash,
  retry/error summary, and redaction flags. They do not include raw request
  payloads, response bodies, headers, endpoints, tokens, or authorization data.
- Added regression coverage for retry-then-success, retry exhaustion, timeout
  exhaustion, rejection, malformed response status, missing transport guard, and
  invalid result guardrails.

## Boundary

Slice 0725 does not create a real network transport and does not wire live HTTP
delivery into the worker. Later S73 slices can attach router logic and protected
smoke evidence using this injectable foundation.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `31 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
