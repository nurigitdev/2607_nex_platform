# Slice 0822: AG acknowledgement expiry automation policy

## Objective

Define the safe configuration contract for externally scheduled S83 expiry
reconciliation runs.

## Policy

- Automation is disabled by default.
- Explicit enablement uses `NEX_AG_ACK_EXPIRY_AUTOMATION_ENABLED`.
- Batch size defaults to `50` and is bounded to `1..200`.
- External cadence defaults to `60` seconds and is bounded to `10..3600`.
- Every execution requires explicit tick confirmation.
- The external scheduler owns cadence; S83 starts no continuous loop or
  subprocess.
- The policy reuses `ag_op_review_ack_state`,
  `service_operational_events`, and the S82 reconciliation executor.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_liveness_ack_expiry_automation_policy.py -q --tb=short
```

Focused regression result: `6 passed`.

Full regression result: `5424 passed, 1 warning`.

- Statement coverage: `69372 / 70255 = 98.743149953740%`.
- Branch coverage: `16413 / 17064 = 96.184950773558%`.
- Policy module statement/branch coverage: `100% / 100%`.
