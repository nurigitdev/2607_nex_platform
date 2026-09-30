# Slice 1136: MO job-control OpenAPI alignment

## Goal

Document the four shared service-local job-control operations already mounted
by the MO runtime, then run the S114 fifth-Slice Checkpoint Gate.

## Result

- Added read, cancel, retry, and dead-letter replay operations with MO-specific
  operation IDs.
- Added reusable job ID, action request, and redacted job-control response
  components.
- Required service-bearer authorization and documented standard not-found and
  transition failures.
- Runtime behavior and database schema are unchanged; this Slice closes four
  documentation-only drift findings.
- Remaining drift is the service root and three log-retention operations.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/pytest -q \
  tests/test_mo_job_control_openapi_contract.py \
  tests/test_mo_contract_api_drift_audit.py
./.venv/bin/python \
  scripts/smoke/run_mo_job_control_openapi_contract.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_job_control_openapi_contract.py
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_mo_job_control_openapi_contract.py \
  --coverage-target scripts/smoke/run_mo_job_control_openapi_contract.py \
  --smoke scripts/smoke/run_mo_job_control_openapi_contract.py
```

## Quality Evidence

- Job-control evidence: operations `4/4`; remaining drift `4`.
- Focused regression: `27 passed`.
- Slice Gate: `433 passed`; statement coverage `99.67%`; branch coverage
  `98.73%`.
- Checkpoint Gate: `8,594 passed`, `5` protected PostgreSQL tests skipped;
  statement coverage `98.73%`; branch coverage `96.88%`.
- Changed smoke scope: statement and branch coverage `100.00%`.
- Contract validation: `119` schemas, `177` positive examples, `145` negative
  examples, and `7` OpenAPI documents.
