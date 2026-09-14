# Slice 0732: AG dispatch live HTTP transport foundation

## Intent

Add the injectable live HTTP transport foundation for S74 while keeping real
external notification and incident endpoints deferred.

## Implementation

- Added `UrllibDispatchProviderHttpTransport` in
  `services/nex-ag/nex_ag/operator_review_dispatch_execution.py`.
- Added `build_dispatch_live_http_transport` and
  `build_dispatch_live_http_transport_envelope` so loopback smoke and future
  real endpoint smoke can share the same transport interface.
- The transport accepts raw endpoint/token only at the injected transport layer.
  Provider requests, result metadata, dashboards, and smoke evidence continue to
  carry only hashes, safe payloads, status codes, and redacted endpoint hints.
- Network execution is still not wired into the worker router by default.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `35 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
