# Slice 0847: AG recovery notification bounded mock execution integration

## Objective

Execute one persisted S85 recovery notification delivery through the existing
AG escalation dispatch execution worker while keeping live network delivery
disabled.

## Implementation

- Added an optional exact dispatch-ID filter to the existing bounded worker.
- Added `run_recovery_notification_delivery_mock_once(...)` as the S85 adapter.
- The adapter verifies the persisted S85 delivery marker and `MOCK` channel.
- Execution requires explicit `confirm_run=True`, fixes the batch limit to one,
  and forces the existing `mock_first_only` provider mode.
- Existing dispatch actions and safe execution-result metadata persistence are
  reused without a new queue, worker, table, or state machine.

Exact-ID runs read the target with `get_escalation_dispatch()` before applying
the eligible-state check. This avoids dropping the target when another outbox
row appears first under a bounded list query.

## Guardrails

- Only the requested dispatch ID can execute.
- Non-S85 records and non-MOCK channels are rejected.
- Missing confirmation returns `BLOCKED` without mutation.
- Completed deliveries return `NOOP` on a later targeted run.
- External network access and live channels remain disabled.
- Raw payloads, request signatures, idempotency keys, provider secrets, and
  database URLs are omitted from the execution envelope.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_recovery_notification_delivery_execution.py \
  tests/test_nex_ag_operator_review_dispatch_execution.py \
  tests/test_nex_ag_recovery_notification_dispatch_handoff.py
```

- Focused worker regression: `100 passed`.
- Recovery notification delivery module statement/branch coverage: `100% / 100%`.
- Full regression: `5655 passed, 1 warning`.
- Statement coverage: `70817 / 71700` (`98.768479776848%`).
- Branch coverage: `16675 / 17326` (`96.242641117396%`).

The warning is the existing Starlette `TestClient` deprecation warning.
