# Slice 1168: MO runtime observability status policy

## Goal

Harden model/GPU status precedence and bounded resource-pressure thresholds so
operators can distinguish unavailable, degraded, unknown, and healthy states.

## Result

- Centralized process, model identity, precision, GPU evidence, metric
  completeness, and resource-pressure classification in one policy module.
- Preserved strict precedence: missing process, ambiguous process, model
  mismatch, precision mismatch/unverified, missing GPU evidence, incomplete
  metrics, resource pressure, then healthy.
- Added default warning thresholds of 90% model GPU memory share and 85 C,
  configurable through validated environment settings.
- Treated high compute utilization as useful work rather than degradation;
  only memory/temperature pressure changes the status.
- Invalidated the TTL cache when either threshold changes.
- Kept policy failures privacy-safe and independent from service readiness.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_runtime_observability_policy.py \
  tests/test_mo_runtime_observation_collector.py \
  tests/test_mo_runtime_observability_service.py
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observability_policy.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_runtime_observability_policy.py \
  --coverage-target services/nex-mo/nex_mo/runtime_observability_policy.py \
  --smoke scripts/smoke/run_mo_runtime_observability_policy.py
```

## Quality Evidence

- Focused policy, collector, and service regression: `59 passed`; all changed
  scopes statement/branch `100%/100%`.
- Slice Gate: `731 passed`, `2` protected PostgreSQL skips.
- Repository coverage: statement `99.80%`, branch `99.26%`; policy, collector,
  and service scopes remained `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Policy evidence passed all five checks at 90% memory and 85 C warning
  thresholds, including high-utilization healthy behavior.
