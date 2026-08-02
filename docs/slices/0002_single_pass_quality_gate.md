# Slice 0002 Single-Pass Quality Gate Bootstrap

Status: Implemented.

Backlog candidate: `S1-002` Single-pass quality gate bootstrap.

## Scope

Slice 0002 adds the first regression and coverage gate:

- `pyproject.toml` pytest and coverage configuration.
- `requirements-dev.txt` for test-only dependencies.
- `scripts/quality/run_quality_gate.sh`.
- `scripts/quality/check_coverage_thresholds.py`.
- Regression tests for backend service shells, environment loading, smoke
  helpers, dev process helpers, and coverage threshold evaluation.
- [Development Process](../development_process.md) baseline.

## Development Process Decision

Every source-code slice should run one quality gate command:

```bash
scripts/quality/run_quality_gate.sh
```

The command uses pytest options to run regression testing and collect statement
plus branch coverage in one pytest invocation:

```bash
./.venv/bin/python -m pytest --cov=services --cov=scripts --cov-branch
```

Thresholds:

| Metric | Minimum |
| --- | ---: |
| Statement coverage | 95% |
| Branch coverage | 85% |

## Refactoring Rule

Before adding functionality, inspect the existing source structure. If the
feature does not fit cleanly, make the smallest enabling refactor first. Larger
refactors should be split into a separate slice.

## Evidence

Quality gate result:

```text
41 passed
statement_coverage=100.00% threshold=95.00%
branch_coverage=100.00% threshold=85.00%
```

Additional checks:

```bash
git diff --check
```

## Follow-Up

Slice 0003 should create the contract package bootstrap from
[Common Schema + Contract Package Layout](../33_common_schema_contract_package_layout.md).
