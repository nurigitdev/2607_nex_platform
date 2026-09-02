# Slice 0528: AG scheduler daemon attention classification

## Scope

- Classify AE scheduler daemon posture for AG operators without giving AG
  direct scheduler, lease, JobQueue, or artifact persistence authority.
- Make lease unavailable, JobQueue unavailable, batch-window blocked, policy
  blocked, and latest dispatch review states explicit in AG metadata.
- Reuse the Slice 0527 automation dashboard rollup so operators can see both
  daemon readiness and the reason category in one surface.

## Implementation

- Added `ag_artifact_operation_retention_daemon_attention.v1` classification
  output to the AG artifact operation daemon projection.
- `summarize_artifact_retention_daemon_operations` now includes
  `attention_status`, `attention_level`, `attention_reason_codes`, and
  `attention_operator_actions`.
- The artifact retention automation dashboard summary now exposes
  `daemon_attention_status`, `daemon_attention_level`,
  `daemon_attention_reason_codes`, and `daemon_attention_operator_actions`.
- The mock automation smoke checks that daemon attention is classified as
  `READY` when manual tick-once is safe and daemon start remains policy-blocked.

## Guardrails

- `start_daemon` and continuous loop execution remain blocked from AG.
- Dispatch observations are classified as `DISPATCH_ATTENTION` so operators
  review the latest manual tick-once result instead of assuming the daemon is
  running continuously.
- Missing daemon config is informational and does not create operator attention
  by itself; lease, queue, batch-window, policy, and dispatch states do.

## Evidence

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_artifact_operations.py \
  tests/test_ag_artifact_retention_automation_operations_smoke.py \
  -q --cov=nex_ag.artifact_operations \
  --cov=run_ag_artifact_retention_automation_operations_smoke \
  --cov-branch --cov-report=term-missing
```

Result: 67 passed, with branch-aware coverage staying above the project gate.
