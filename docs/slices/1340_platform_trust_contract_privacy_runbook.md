# Slice 1340: Platform trust contract, privacy, and runbook hardening

## Outcome

- Published strict schemas and indexed positive and negative fixtures for the
  signed OA user-login response and privacy-safe active service claim.
- Added the signed internal user-login route to OA OpenAPI and the sensitive
  active-claim route to AE, CX, MO, and AG OpenAPI with exact route class,
  scope, and fail-closed response contracts.
- Added an operator runbook covering protected execution, expected evidence,
  failure triage, cleanup verification, rollback, secret handling, and the
  remote-provider boundary.
- Added deterministic hardening evidence for contract presence, index
  registration, privacy rejection, cleanup finalization, canonical status, and
  the explicit exclusion of remote model providers.
- Kept database URLs, credentials, browser sessions, bearer values, private
  keys, and provider secrets out of committed evidence.

## Verification

```bash
PYTHONPATH=services/_shared:scripts/smoke ./.venv/bin/pytest -q \
  tests/test_platform_trust_operations_hardening.py \
  tests/test_contract_validation.py \
  --cov=run_platform_trust_operations_hardening --cov-branch \
  --cov-report=term-missing \
  --cov-report=json:reports/quality/slice-1340.coverage.json
./.venv/bin/python scripts/quality/check_coverage_scopes.py \
  reports/quality/slice-1340.coverage.json 95 94 \
  scripts/smoke/run_platform_trust_operations_hardening.py
./.venv/bin/python scripts/smoke/run_platform_trust_operations_hardening.py \
  --summary
./.venv/bin/python scripts/quality/validate_contracts.py
```

- Focused regression: 32 passed.
- Changed-scope coverage: 100.00% statement and 100.00% branch.
- Operations hardening: 11/11 checks passed across four active-claim services
  and six contract artifacts.
- Contract validation: 158 schemas, 216 examples, 186 negative examples, and
  seven OpenAPI documents.
- Slice 1339 remains the actual PostgreSQL/process trust evidence; Slice 1340
  performs no remote model-provider calls and introduces no new database state.
