# Slice 0827: AG acknowledgement expiry automation operations projection

## Objective

Expose acknowledgement expiry automation policy, scheduler posture, and recent
lifecycle outcomes in the existing NeX-AG operations dashboard.

## Behavior

- The dispatch dashboard includes `ack_expiry_automation` without adding a new
  route or table.
- Statuses distinguish `DISABLED`, `WAITING_FIRST_RUN`, `RUNNING`, `HEALTHY`,
  `ATTENTION`, `DEGRADED`, and `SOURCE_UNAVAILABLE`.
- Policy batch/cadence settings and the external scheduler command shape are
  visible to operators.
- Recent lifecycle events expose identifiers, status, and aggregate counts only.
- Event-source failures are degraded safely without exposing exception details.
- The strict operations schema and canonical dashboard fixture require the new
  section.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_liveness_ack_expiry_automation_operations.py \
  -q --tb=short
```

Focused regression result: `34 passed`.

Contract validation result:
`schemas=77, examples=123, negative_examples=87, openapi=7` passed.

Full regression result: `5470 passed, 1 warning`.

- Statement coverage: `69587 / 70470 = 98.746984532425%`.
- Branch coverage: `16457 / 17108 = 96.194762684124%`.
- Operations projection module statement/branch coverage: `100% / 100%`.
