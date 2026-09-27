# Slice 1008: AE contract and API drift audit

## Goal

Compare AE API source routes with the checked-in OpenAPI document and verify
positive and negative fixture coverage for AE-owned schemas.

## Decision

- Runtime source currently declares 71 literal AE operations. OpenAPI documents
  43 of them and omits 28, primarily artifact-retention operations.
- Five shared compatibility, recovery-policy, and prompt-registry operations are
  documented through the shared runtime and are not treated as stale entries.
- Twenty-two AE-owned schemas have 20 positive and 19 negative fixture links.
- The OpenAPI version remains `0.0.0-slice0003` and is stale.
- The 34 classified drift items become an S102 contract-hardening input. S101
  does not change public behavior or silently publish an incomplete contract.
- New public AE routes must not be added before the OpenAPI baseline is current.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_ae_contract_api_drift_audit.py --summary
./.venv/bin/pytest -q tests/test_ae_contract_api_drift_audit.py \
  --cov=nex_ae_api.contract_api_drift_audit \
  --cov=run_ae_contract_api_drift_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

- Audit: PASS with readiness `GAPS_CONFIRMED`; runtime operations `71`, OpenAPI
  operations `52`, directly covered runtime operations `43`, and missing
  operations `28`.
- Fixture coverage: positive `20/22`, negative `19/22`; total classified drift
  items `34`; audit execution issues `0`.
- Focused tests: `4 passed`; the audit module and runner both reached `100%`
  statement and branch coverage.
- Slice Gate: `1,891 passed`; statement coverage `97.77%`; branch coverage
  `95.46%`.
- Contract validation: `92` schemas, `145` examples, `109` negative examples,
  and `7` OpenAPI documents passed.
