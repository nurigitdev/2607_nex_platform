# Slice 1171: S117 MO GPU and model runtime observability closure

## Goal

Close S117 with deterministic domain, collector, cache, policy, authenticated
API, contract, privacy, protected DGX, traceability, and Full Gate evidence.

## Result

- Superseded the S111 `MO-FR-005` partial baseline with an S117
  `IMPLEMENTED` decision while preserving the historical S111 audit.
- Closed model identity, loaded BF16 dtype, process liveness, GPU association,
  per-process allocation, unified/discrete memory capacity, utilization, and
  temperature observation for all three selected capabilities.
- Closed an authenticated diagnostic API with bounded force refresh, 30-second
  process-local TTL, fail-closed status policy, canonical schema, OpenAPI, and
  private-value omission.
- Preserved diagnostic-only readiness composition and no-table persistence;
  S117 requires no PostgreSQL migration or PostgreSQL smoke.
- Registered all ten S117 evidence runners in the Full Gate. The protected DGX
  runner skips by default; its separately executed live evidence is required by
  the closure document checks.
- Handed MO catalog and alias lifecycle management to S118.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s117_mo_gpu_model_runtime_observability_closure.py
./.venv/bin/python \
  scripts/smoke/run_s117_mo_gpu_model_runtime_observability_closure.py \
  --summary
scripts/quality/run_quality_gate.sh
```

## Quality evidence

- Focused closure regression: `6 passed`; closure evidence passed `9/9`
  runners and `5/5` components with all three runtime models closed.
- Full Gate: `9,410 passed`, `7` protected smoke skips, and `123` warnings in
  `1,129.70s`.
- Repository coverage remained above policy at statement `98.76%` and branch
  `97.01%`.
- Contract validation passed `120` schemas, `178` positive examples, `146`
  negative examples, and `7` OpenAPI documents.
- AE Web Node regression passed `293/293` tests.
- All ten S117 evidence runners completed in the Full Gate. The protected DGX
  runner skipped by default while the separately executed Slice 1170 evidence
  remained `3/3` for models, precision, and GPU metrics.
