# Slice 0747: AG dispatch execution daemon protected control foundation

## Intent

Define the protected control request and admission boundary for dispatch daemon
tick planning and tick execution before adding route wiring or PostgreSQL smoke
coverage.

## Implementation

- Added `build_dispatch_execution_daemon_control_request`.
- Added `build_dispatch_execution_daemon_control_admission`.
- Supported actions are limited to `tick_plan` and `tick_once`.
- `tick_once` admission requires the daemon policy to be enabled and
  `confirm_tick=True`.
- Control request output stores only safe fields and a request hash; raw payloads,
  tokens, provider payloads, and incomplete operator refs are omitted.
- No new table, route, background loop, or persistent control store is introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `50 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
