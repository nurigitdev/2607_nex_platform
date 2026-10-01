# Slice 1190: MO protected DGX and PostgreSQL live acceptance

## Goal

Prove the integrated MO operations surface against the actual test database,
three DGX vLLM providers, and protected SSH runtime observation.

## Result

- Added fail-closed admission requiring the explicit S119 live flag, `test`
  profile, exact `nex_mo_user@nex_mo_test` identity, all three direct-vLLM
  provider configurations, and a validated DGX SSH target.
- Sends one real embedding, reranking, and generation request and records the
  outcomes through the durable PostgreSQL telemetry store.
- Forces live route readiness and SSH runtime/GPU observation while composing
  the authenticated operations snapshot from the durable catalog.
- Requires all four sources and all three capabilities to be ready, all three
  runtime models to be healthy, expected provider models to match, and the
  canonical response schema to validate.
- Uses unique telemetry deployment identities and targeted cleanup; evidence
  excludes endpoints, credentials, database passwords, SSH targets, raw
  provider payloads, and process commands.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_operations_live_acceptance.py
NEX_MO_OPERATIONS_LIVE_ACCEPTANCE=1 \
NEX_MO_OPERATIONS_LIVE_ACCEPTANCE_PROFILE=test \
NEX_MO_PROVIDER_MODE=live \
NEX_MO_TEST_DATABASE_URL='<protected nex_mo_test URL>' \
./.venv/bin/python scripts/smoke/run_mo_operations_live_acceptance.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

## Executed evidence

- The first integrated attempt failed closed on the generation probe; provider
  isolation confirmed all three endpoints were healthy, and the probe was
  aligned with the established non-reasoning request shape.
- The protected runner then passed all `13/13` checks against
  `nex_mo_user@nex_mo_test` and DGX: provider requests `3/3`, expected models
  `3/3`, ready sources `4/4`, healthy runtime capabilities `3/3`, and cleanup
  residue `0`.
- The protected pytest case independently passed against the actual PostgreSQL,
  HTTP provider, and SSH runtime boundaries.
- The Slice Gate passed `928` tests with `5` protected smoke skips and `1`
  warning in 72 seconds; statement coverage was `99.86%` and branch coverage
  was `99.50%`.
