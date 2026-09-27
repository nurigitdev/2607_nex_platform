# Slice 1002: AE current-state re-audit boundary

## Goal

Start S101 by freezing the combined NeX-AE API and Web current-state re-audit
boundary before adding another AE feature or schema.

## Decision

- The audit covers `AEAPI-FR-001` through `AEAPI-FR-006` and `AEWEB-FR-001`
  through `AEWEB-FR-005`.
- Repository code, migrations, contracts, browser modules, and executable
  evidence are primary. Historical gap notes remain advisory.
- Refactoring precedes feature work only where evidence proves stale coupling,
  duplicated ownership, an unsafe private-data boundary, or an oversized module
  that blocks isolated change.
- S101 requires actual `nex_ae_test` evidence and deterministic browser runtime
  evidence before closure. Live DGX provider access is not required.
- Slice 1002 adds no table or migration and does not mutate AE records.
- Production identity-provider activation, object storage, and browser load/DR
  certification remain deferred.

## Slice Plan

1. Slice 1002: current-state boundary audit.
2. Slice 1003: AE API/Web capability traceability inventory.
3. Slice 1004: persistence gap re-baseline.
4. Slice 1005: authentication, ownership, and privacy enforcement audit.
5. Slice 1006: runtime coupling/refactoring checkpoint.
6. Slice 1007: database and migration drift audit.
7. Slice 1008: contract and API drift audit.
8. Slice 1009: Web runtime, i18n, and accessibility drift audit.
9. Slice 1010: actual PostgreSQL re-audit and privacy runbook.
10. Slice 1011: S101 closure and S102 handoff.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ae_current_state_reaudit_boundary.py --summary

./.venv/bin/pytest -q \
  tests/test_ae_current_state_reaudit_boundary.py \
  --cov=run_ae_current_state_reaudit_boundary \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
boundary audit: PASS
focused tests: 5 passed
boundary runner statement/branch coverage: 100%
Slice Gate: 1,859 passed, 1 known warning
statement coverage: 97.71%
branch coverage: 95.39%
contract validation: 92 schemas, 145 examples, 109 negative examples, 7 OpenAPI
```
