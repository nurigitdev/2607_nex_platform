# Slice 1116: MO provider HTTP transport extraction

## Goal

Separate remote JSON transport and provider failure classification from request
composition, response normalization, and telemetry while preserving injection.

## Result

- `nex_mo.provider_transport` owns JSON HTTP execution and failure decisions.
- Timeout, connection, throttling, upstream 5xx/4xx, and malformed JSON
  projections retain their existing status, retryable, and degraded semantics.
- `nex_mo.remote_provider` preserves compatibility exports.
- Requester injection remains the deterministic test and protected-smoke seam.
- Retry execution is intentionally deferred to S115; this Slice only clarifies
  the single-attempt transport boundary.
- No table, migration, or live provider request is introduced.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_transport_extraction.py \
  tests/test_nex_mo_remote_provider.py \
  --cov=nex_mo.provider_transport \
  --cov=run_mo_provider_transport_extraction \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_transport_extraction.py --summary

scripts/quality/run_checkpoint_gate.sh \
  --coverage-target services/nex-mo/nex_mo/provider_transport.py \
  --smoke scripts/smoke/run_mo_provider_transport_extraction.py
```

Observed Checkpoint Gate evidence:

- `8,457 passed`, `5 skipped`, `123 warnings`.
- Statement coverage: `98.72%`.
- Branch coverage: `96.86%`.
- Provider transport statement and branch coverage: `100%`.
- Contract validation: 109 schemas, 167 positive examples, 132 negative
  examples, and 7 OpenAPI documents.
