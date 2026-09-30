# Slice 1140: MO contract API PostgreSQL smoke

## Goal

Prove the S114 API contract against the actual `nex_mo_test` database without
calling DGX providers or leaving smoke records behind.

## Result

- Added an explicit test-only protected smoke gate that rejects any database
  other than `nex_mo_user@nex_mo_test`.
- Runs all MO SQL migrations before exercising persistence.
- Performs real job insert/select/API-read/API-cancel and service-log
  insert/select operations through PostgreSQL adapters.
- Executes retention purge, history list, and history detail routes against
  persisted records.
- Deletes all temporary job, log, and retention-history rows and verifies zero
  residue.
- Evidence excludes credentials, authorization tokens, payloads, and smoke IDs.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_contract_api_postgres_smoke.py
NEX_MO_CONTRACT_API_POSTGRES_SMOKE=1 \
NEX_MO_CONTRACT_API_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python \
  scripts/smoke/run_mo_contract_api_postgres_smoke.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_contract_api_postgres_smoke.py
```

## Quality Evidence

- Protected smoke: `12/12` checks passed against
  `nex_mo_user@nex_mo_test`; migrations were current at `0 applied + 7
  skipped / 7 planned`, three temporary records were written, and cleanup
  residue was `0`.
- Protected pytest: `1 passed` with the opt-in enabled; it was not skipped.
- Default focused regression: `6 passed, 1 protected skip`.
- Slice Gate: `451 passed, 1 protected skip`.
- Statement coverage: `99.67%` (threshold `95%`).
- Branch coverage: `98.73%` (threshold `94%`).
- Contract validation: `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
