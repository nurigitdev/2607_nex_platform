# Slice 1153: MO provider telemetry persistence contract

## Goal

Define the durable identity, atomic mutation, aggregate invariant, and
repository contracts independently of SQL and runtime wiring.

## Result

- `ProviderTelemetryIdentity` fixes the four-field logical key for embedding,
  reranking, and generation aggregates.
- `ProviderTelemetryMutation` distinguishes a final success, final failure,
  and intermediate retry while projecting exact counter increments.
- `DurableProviderTelemetryRecord` enforces non-negative counters,
  `request = success + failure`, and `attempt = request + retry`.
- The repository protocol exposes only atomic apply, bounded list, and
  protected clear operations.
- Persistence mappings contain aggregate diagnostics only. Provider endpoints,
  credentials, authorization, and payloads remain absent.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_persistence_contract.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_persistence_contract.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_telemetry_persistence_contract.py \
  --coverage-target services/nex-mo/nex_mo/provider_telemetry_persistence.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_persistence_contract.py
```

## Quality Evidence

- Focused regression: `24 passed`.
- Slice Gate: `556 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.74%`, branch `99.03%`; changed persistence-contract
  scope `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- The contract smoke proved one logical request, two attempts, one retry, and
  privacy-safe persistence mapping.
