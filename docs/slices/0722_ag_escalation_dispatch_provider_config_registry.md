# Slice 0722: AG dispatch provider config registry hardening

## Intent

Add the safe provider configuration registry needed before AG dispatch execution
can route notification, email, webhook, or incident delivery through HTTP
providers.

## Implementation

- Added `build_dispatch_execution_provider_config(...)` to expose provider mode,
  live activation guard, HTTP timeout/retry settings, endpoint readiness, and
  live provider profile metadata.
- Added environment-driven provider mode normalization with allowed values:
  `mock_first_only`, `mock_http`, and `live_http`.
- Added safe HTTP defaults and bounds for timeout, connect timeout, read
  timeout, retries, and backoff.
- Added redacted endpoint hints for notification/webhook and external incident
  providers. Raw endpoint paths, service tokens, API keys, database URLs,
  idempotency keys, and provider payloads remain excluded from the config
  output.
- Added regression coverage for default config, env overrides, clamping,
  malformed values, live activation guard behavior, redacted endpoint hints, and
  unsupported provider modes.

## Boundary

Slice 0722 does not perform outbound HTTP calls and does not activate live
provider delivery. `live_http` remains guarded by
`NEX_AG_DISPATCH_LIVE_PROVIDER_ENABLE=1`; otherwise the effective mode falls
back to `mock_http`.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `20 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
