# Slice 0733: AG dispatch live HTTP transport request guardrails

## Intent

Make the live HTTP transport request shape inspectable without exposing raw
endpoint URLs, authorization headers, or provider payloads.

## Implementation

- Added `build_dispatch_live_http_transport_headers` for outbound HTTP headers.
- Added `build_dispatch_live_http_transport_request_plan` as the safe evidence
  view for live HTTP sends.
- The request plan records only the redacted endpoint hint, request/envelope
  hashes, header names safe for evidence, and whether an Authorization header is
  configured.
- Authorization values, raw endpoint paths, and raw header values remain
  withheld from evidence.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `36 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
