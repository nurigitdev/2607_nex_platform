# Slice 1150: MO provider resilience contract hardening

## Goal

Keep the existing authenticated telemetry API aligned with the canonical retry
schema and runtime response without reopening S114 operation drift.

## Result

- OpenAPI now documents every provider telemetry item field explicitly and
  references that item from the existing snapshot response.
- Five retry fields are required consistently by canonical JSON Schema,
  OpenAPI, fixture, and runtime API response.
- A fail-closed contract audit compares property and required-field sets,
  validates authenticated runtime output, and rejects private runtime keys.
- The runtime/OpenAPI operation count remains `19` with zero drift. No new API,
  database table, or external provider dependency is introduced.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_resilience_contract.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_resilience_contract.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_resilience_contract.py \
  --coverage-target services/nex-mo/nex_mo/provider_resilience_contract.py \
  --smoke scripts/smoke/run_mo_provider_resilience_contract.py
```

## Quality Evidence

- Focused contract, drift, OpenAPI, and provider API regression: `63 passed`.
- Slice Gate: `522 passed`, `1` protected PostgreSQL smoke skip.
- Coverage: statement `99.72%`, branch `98.95%`; changed contract-audit scope
  reached statement `100.00%` and branch `100.00%`.
- Contract validation remained `119/177/145/7`.
- Authenticated runtime evidence covered three telemetry items, all five retry
  fields, and zero runtime/OpenAPI operation drift (`4/4` checks).
