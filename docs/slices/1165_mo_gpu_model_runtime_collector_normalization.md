# Slice 1165: MO GPU and model runtime collector normalization

## Goal

Execute the fixed protected collector and normalize DGX process/GPU evidence
into the S117 runtime domain without returning host-private identifiers.

## Result

- Added a fixed SSH Python-stdin collector that correlates the configured vLLM
  process trees with NVIDIA compute applications and device metrics.
- The remote side uses process IDs, command lines, model paths, and GPU UUIDs
  only for correlation. None of those values are returned in its raw payload.
- Normalized process count, expected-model match, runtime dtype, GPU count,
  process GPU memory, device capacity, utilization, and temperature for all
  three capabilities.
- Classified missing/ambiguous processes, model mismatch, precision mismatch,
  unverified dtype, and unavailable GPU evidence with stable safe codes.
- Mapped SSH timeout, execution, output, and payload failures to bounded error
  codes without carrying exception or command details.
- Kept mock collection deterministic and completely offline.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_runtime_observation_collector.py
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observation_collector.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_runtime_observation_collector.py \
  --coverage-target \
  services/nex-mo/nex_mo/runtime_observability_collector.py \
  --smoke scripts/smoke/run_mo_runtime_observation_collector.py
```

## Quality Evidence

- Focused collector regression: `22 passed` with statement/branch
  `100%/100%`.
- Slice Gate: `683 passed`, `2` protected PostgreSQL skips.
- Repository coverage: statement `99.79%`, branch `99.21%`; changed collector
  scope `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Deterministic evidence collected `3/3` healthy mock models with zero private
  runtime fields; no DGX connection was made in this Slice.
