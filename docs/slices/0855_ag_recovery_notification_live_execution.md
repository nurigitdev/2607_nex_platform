# Slice 0855: AG recovery notification targeted live execution

## Objective

Execute one explicitly selected recovery-notification dispatch through the
existing live HTTP worker path and project only safe provider diagnostics.

## Implementation

- Added `run_recovery_notification_delivery_live_once(...)`.
- Rechecks the persisted recovery marker, notification channel, effective live
  mode, endpoint readiness, profile/channel compatibility, explicit
  confirmation, and injected transport at execution time.
- Uses batch limit one plus an exact dispatch-id filter and routes all state
  changes through the existing dispatch action state machine.
- Persists the existing safe execution-result metadata only.
- Recovery delivery operations items now expose bounded safe execution status,
  provider mode/category/profile, result hashes, HTTP status, attempt count,
  retry state, safe preview, and timestamps.
- Endpoint values, headers, tokens, raw payloads, and idempotency keys remain
  absent.

## Verification

```bash
./.venv/bin/pytest -q --tb=short \
  tests/test_nex_ag_recovery_notification_live_execution.py \
  tests/test_nex_ag_recovery_notification_delivery_execution.py \
  tests/test_nex_ag_recovery_notification_operations.py \
  --cov=nex_ag.recovery_notification_delivery \
  --cov=nex_ag.recovery_notification_operations --cov-branch
```
