# Slice 0639: AG Operator Review Workbench Privacy Regression

Slice 0639 adds a mock-first privacy regression pack for the AG operator review
workbench surfaces.

## Scope

- Adds `scripts/smoke/run_ag_operator_review_workbench_privacy_regression.py`.
- Builds defensive in-memory note/export records that intentionally include
  unsafe extra fields such as raw note text, raw evidence body, prompt/source
  text, storage path, raw idempotency key, service token, provider key, and a
  database URL.
- Drives the protected workbench, rollup, operations dashboard, and
  issue-candidate routes through `TestClient`.
- Fails if any forbidden sensitive value appears in those output surfaces.
- Verifies the intended bounded note-preview behavior without allowing the raw
  note sentinel through.

## Boundary

- No database schema or runtime persistence change.
- No real PostgreSQL smoke is added here; Slice 0638 remains the protected
  `nex_ag_test` PostgreSQL evidence slice for the same workbench capability.
- Evidence stores leak labels and counts only, never the forbidden raw values.

## Verification

```bash
PYTHONPATH=scripts/smoke:services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_ag_operator_review_workbench_privacy_regression.py -q --cov=run_ag_operator_review_workbench_privacy_regression --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/smoke/run_ag_operator_review_workbench_privacy_regression.py --summary
./scripts/quality/run_quality_gate.sh
```
