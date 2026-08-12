# Slice 0230: AE Web Fetch-Mode Smoke Evidence Contract Closure

## Scope

Slice 0230 closes the S23 AE Web fetch-mode track by freezing the protected
PostgreSQL smoke evidence shape as a contract.

Implemented:

- Added
  `contracts/schemas/service/nex_ae_web/fetch_mode_smoke_evidence.v1.schema.json`.
- Added a positive PASS fixture for AE/CX test DB readback evidence.
- Added a negative fixture that rejects raw PostgreSQL credentials in the
  redacted database URL fields.
- Registered both fixtures in the contract validation indexes.
- Added regression tests that validate the fixtures and confirm generated
  Slice 0229 PASS evidence conforms to the contract.
- Updated AE Web and working-doc indexes to include the Slice 0230 closure.

## Boundary

The contract intentionally covers PASS evidence only. Skip and failure summaries
remain runner control-flow states; the durable evidence that operators need is
the proof that a protected run:

- used the `test` profile;
- targeted `NEX_AE_TEST_DATABASE_URL` and `NEX_CX_TEST_DATABASE_URL`;
- exposed only redacted database URLs;
- ran AE/CX migrations;
- wrote/read the AE smoke marker;
- exercised AE upload, document detail, and retrieval facade calls;
- read back CX retrieval evidence from PostgreSQL;
- cleaned up smoke rows after execution.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_ae_web_fetch_mode_postgres_smoke.py tests/test_contract_validation.py -q
```

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
37 passed, 1 warning in 2.50s
```

Observed contract validation:

```text
contract_validation=pass schemas=48 examples=77 negative_examples=53 openapi=7
```

Observed full quality gate:

```text
1667 passed, 1 warning in 56.38s
statement_coverage=98.04% threshold=95.00%
branch_coverage=93.88% threshold=85.00%
contract_validation=pass schemas=48 examples=77 negative_examples=53 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
