# Slice 1158: MO authenticated durable telemetry API projection

## Goal

Prove the authenticated provider telemetry API reads restart-safe aggregates
without changing the existing v1 wire contract or leaking persistence details.

## Result

- `GET /api/v1/provider-telemetry` reads the injected durable store after a new
  repository and store instance are constructed.
- Service-claim authentication and capability filtering remain unchanged.
- The response retains the 26-field telemetry item and existing
  `mo_provider_telemetry_snapshot.v1` metadata.
- Provider endpoints, API keys, database URLs, and repository implementation
  details remain absent from successful responses.
- Repository failures become a bounded, privacy-safe `503` problem response
  with `MO_PROVIDER_TELEMETRY_UNAVAILABLE` rather than exposing exceptions.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_durable_api.py \
  tests/test_mo_provider_telemetry_durable_api_smoke.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_durable_api.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_telemetry_durable_api.py \
  --test tests/test_mo_provider_telemetry_durable_api_smoke.py \
  --coverage-target services/nex-mo/nex_mo/providers.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_durable_api.py
```

## Quality Evidence

- Focused API and existing provider-route regression: `54 passed`.
- Slice Gate: `594 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.76%`, branch `99.07%`; changed provider API scope
  statement `100%`, branch `97.62%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Durable API smoke proved unauthenticated `401`, authenticated `200`, all 26
  telemetry fields, restart recovery, private-value redaction, and cleanup.
