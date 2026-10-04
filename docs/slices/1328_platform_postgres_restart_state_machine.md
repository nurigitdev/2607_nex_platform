# Slice 1328: Platform PostgreSQL restart state machine

## Outcome

- Added one coordinator above migration readiness, service-owned API/worker
  pools, and the S132 runtime process orchestrator.
- Enforced startup as migration gate, fresh pool construction, then process
  readiness; failures are normalized without projecting connection details.
- Enforced shutdown as reverse process termination followed by pool disposal,
  including best-effort cleanup of both layers when either layer fails.
- Enforced one fresh restart generation and rejected any engine identity reused
  from the prior generation.

## Decision

The coordinator owns lifecycle sequencing, not service business work. It does
not claim jobs, invoke model providers, write durable sentinels, or contain
PostgreSQL credentials. Slice 1329 owns durable restoration semantics and
Slice 1330 composes this state machine with real test databases and processes.

Invalid duplicate commands are rejected without poisoning a healthy running
generation. Operational startup, health, shutdown, and freshness failures move
the coordinator to `FAILED` after cleanup has been attempted.

## Verification

- Focused regression: `18 passed`; both changed modules reached statement and
  branch coverage `100%`.
- Deterministic lifecycle smoke: `PASS`; two migration gates, two generations,
  one restart, ten fresh engine identities, and reverse shutdown ordering were
  confirmed without claiming actual PostgreSQL execution.
- Slice Gate: `952 passed, 11 skipped`; statement coverage `98.46%`, branch
  coverage `97.75%`, and all five gate commands passed.
- Contract validation: `156` schemas, `214` examples, `184` negative examples,
  and `7` OpenAPI documents passed.
