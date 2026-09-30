# Slice 1159: MO provider telemetry durability contract hardening

## Goal

Align migration, repository, runtime, authenticated API, canonical schema,
OpenAPI, privacy controls, and the MO operations runbook before PostgreSQL
evidence is collected.

## Result

- OpenAPI now describes restart-safe aggregate telemetry and the safe `503`
  repository-unavailable response instead of process-local-only behavior.
- Canonical JSON Schema and explicit OpenAPI fields remain exactly aligned at
  26 required telemetry item fields.
- The migration audit verifies the compact table, five identity columns, seven
  counters, schema registry entry, and absence of eight private column classes.
- Repository guards require atomic increments and monotonic final/retry
  observation updates.
- Runtime guards preserve deterministic memory mode, durable PostgreSQL mode,
  and privacy-safe API failure projection.
- The MO runbook now documents both persistence modes and the owned table.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_durability_contract.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_durability_contract.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_telemetry_durability_contract.py \
  --coverage-target \
  services/nex-mo/nex_mo/provider_telemetry_durability_contract.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_durability_contract.py
```

## Quality Evidence

- Focused durability and prior resilience-contract regression: `10 passed`.
- Slice Gate: `599 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.76%`, branch `99.08%`; changed durability-contract
  scope `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Durability audit aligned `26` wire fields and `24` table columns, including
  all five identity and seven counter columns with zero forbidden columns and
  zero failed checks.
