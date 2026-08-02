# NeX-Platform Development Process

Status: Baseline for Slice 0002.

This process applies to implementation slices after the Slice 0000
documentation baseline. It keeps feature work small, regression-tested, and
aligned with service ownership.

## Quality Gate

Run the single-pass quality gate for every source-code slice:

```bash
scripts/quality/run_quality_gate.sh
```

The command runs pytest regression tests and collects statement and branch
coverage in the same pytest invocation:

```bash
./.venv/bin/python -m pytest --cov=services --cov=scripts --cov-branch
```

Coverage thresholds:

| Metric | Minimum |
| --- | ---: |
| Statement coverage | 95% |
| Branch coverage | 85% |

The quality gate writes local coverage output under `reports/coverage/`.
Reports are local evidence and are not committed by default.

## Slice Start Checklist

Before adding source code in a slice:

1. Confirm `git status --short --branch` is understood.
2. Read the relevant requirement IDs, contracts, and slice notes.
3. Inspect the current source tree around the target change.
4. Identify the owning service and database/API boundary.
5. Decide whether a small structural cleanup is needed before feature work.

## Refactoring Rule

Feature work starts by reading the existing structure. If the current structure
cannot naturally accept the feature, do a small refactor first inside the same
slice only when it directly enables the requested change.

Large or cross-cutting refactors should become their own slice. Do not mix a
large refactor with new domain behavior.

## Regression Rule

Every source-code slice should leave one clear regression signal:

- `scripts/quality/run_quality_gate.sh` passes.
- Statement and branch coverage meet the thresholds, or a written exception is
  recorded in the slice note.
- New behavior has focused tests at the unit, API, contract, or smoke layer
  appropriate to its risk.
- `git diff --check` passes.

Documentation-only slices may use the docs-only rule from
[Testing Strategy v0.1 Detail](34_testing_strategy_v0_1_detail.md): link/keyword
checks plus `git diff --check`, unless executable examples or schemas changed.

## Service Boundary Rule

Do not use `_shared` as a place for service-private domain logic. Shared code
should remain limited to cross-service shell behavior, environment loading,
contract primitives, trace/error helpers, and test utilities until duplication
creates a clear implementation cost.
