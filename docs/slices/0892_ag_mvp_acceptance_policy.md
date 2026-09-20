# Slice 0892: AG MVP acceptance policy

## Goal

Freeze one validated policy for deciding whether the NeX-AG service MVP may
close and whether implementation focus may move to NeX-CX.

## Policy

- All eight acceptance gates are blocking and require `PASS`. `SKIPPED` never
  satisfies a required gate.
- Aggregate regression requires at least 6,000 passing tests and zero failures.
- S90 raises its service-acceptance coverage defaults to 98% statement and 96%
  branch coverage. The project-wide 95%/85% floors remain visible but are not
  sufficient for this closure.
- PostgreSQL evidence must identify the `postgresql` backend and actual
  `nex_ag_test` database, and must leave no test residue.
- Acceptance evidence is server-derived, privacy-safe, and no older than 24
  hours by default.
- Advisory production deferrals stay visible but do not block the development
  transition to NeX-CX.

## Configuration

| Variable | Default | Bounds |
| --- | ---: | ---: |
| `NEX_AG_MVP_MIN_STATEMENT_COVERAGE` | `98.0` | `95.0` to `100.0` |
| `NEX_AG_MVP_MIN_BRANCH_COVERAGE` | `96.0` | `85.0` to `100.0` |
| `NEX_AG_MVP_EVIDENCE_MAX_AGE_HOURS` | `24` | `1` to `168` |
| `NEX_AG_MVP_REQUIRED_REGRESSION_TESTS` | `6000` | `1` to `1000000` |

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_mvp_acceptance.py \
  --cov=nex_ag.mvp_acceptance --cov-branch --cov-report=term-missing
```

Observed verification:

```text
policy tests: 14 passed
policy module statement/branch: 100%
aggregate regression: 6178 passed, 1 known warning
statement=74917/75798=98.837700203172%
branch=17500/18150=96.418732782369%
```
