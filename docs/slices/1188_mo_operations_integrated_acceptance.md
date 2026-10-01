# Slice 1188: MO deterministic integrated operations acceptance

## Goal

Exercise the complete MO operations projection with production in-memory
components before PostgreSQL and DGX protected evidence is admitted.

## Result

- Bootstrapped the real in-memory model catalog and active alias lifecycle.
- Composed the real readiness evaluator/cache, telemetry store, runtime
  observability service, operations service, authentication guard, and API.
- Verified both baseline and `force_refresh=true` requests produce four fresh
  ready sources and three ready capabilities.
- Validated the runtime response against `mo_operations_snapshot.v1` and
  asserted that credentials, endpoints, database URLs, and SSH targets are not
  projected.
- Kept this acceptance deterministic and network-free; it does not claim
  PostgreSQL durability or DGX provider liveness.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_operations_integrated_acceptance.py
./.venv/bin/python scripts/smoke/run_mo_operations_integrated_acceptance.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

## Executed evidence

- Focused acceptance tests passed `5` tests; the deterministic runner reported
  `4/4` ready sources, `3/3` ready capabilities, and zero schema errors.
- The Slice Gate passed `916` tests with `3` protected PostgreSQL smoke skips
  and `1` warning in 73 seconds.
- Statement coverage remained `99.86%` and branch coverage remained `99.50%`;
  contract validation passed `129` schemas, `187` positive examples, `155`
  negative examples, and `7` OpenAPI documents.
