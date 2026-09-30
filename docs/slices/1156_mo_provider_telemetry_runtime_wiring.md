# Slice 1156: MO durable provider telemetry runtime wiring

## Goal

Select the telemetry store from MO persistence mode and make remote execution,
retry callbacks, reset, and authenticated reads share one runtime instance.

## Result

- Memory persistence reuses the established in-memory telemetry store and
  remains database-free.
- PostgreSQL persistence builds the durable adapter from the shared API session
  factory and existing connection pool.
- Remote provider success/failure recording, retry callbacks, telemetry reads,
  and protected resets all resolve the same injected store.
- The selected store is exposed through `app.state.provider_telemetry_store`
  for runtime inspection without publishing credentials or database details.
- The fifth-Slice Checkpoint Gate validates the broader repository regression
  before restart and concurrency hardening continues.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_runtime.py \
  tests/test_mo_provider_telemetry_runtime_smoke.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_runtime.py --summary
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_mo_provider_telemetry_runtime.py \
  --test tests/test_mo_provider_telemetry_runtime_smoke.py \
  --coverage-target services/nex-mo/nex_mo/provider_telemetry_runtime.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_runtime.py
```

## Quality Evidence

- Focused runtime and remote-provider regression: `102 passed` after the
  architecture-budget correction.
- The first Checkpoint Gate correctly detected four failures because added
  wrappers pushed `remote_provider.py` nine lines above its 1,200-line budget.
  Moving store ownership into `provider_telemetry_runtime.py` reduced it to
  1,176 lines and restored both S112 hardening audits.
- Repeated Checkpoint Gate: `8,740 passed`, `6` protected smoke skips.
- Coverage: statement `98.75%`, branch `96.91%`; changed runtime scope
  `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Runtime smoke selected memory and durable stores correctly and projected all
  three provider capabilities through the injected store.
