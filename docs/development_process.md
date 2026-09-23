# NeX-Platform Development Process

Status: Tiered regression baseline for Slice 0971.

This process applies to implementation slices after the Slice 0000
documentation baseline. It keeps feature work small, regression-tested, and
aligned with service ownership.

## Quality Gates

Regression remains mandatory for every source-code Slice. The execution scope
uses three tiers so historical coverage evidence does not dominate ordinary
feature work.

| Tier | Cadence | Scope |
| --- | --- | --- |
| Slice Gate | Every Slice | Owning-service regression, focused tests, changed-source coverage, contracts, and explicitly selected smoke. |
| Checkpoint Gate | Fifth Slice in a requirement, or risk escalation | Platform regression excluding historical `test_s*_closure.py`, service/provider coverage, contracts, and selected smoke. |
| Full Gate | Tenth/closure Slice, release, or explicit escalation | Original complete pytest/coverage run, all historical smoke/closure summaries, contracts, and protected checks selected by environment. |

The cadence is requirement-relative. It does not depend on the final digit of
the repository Slice number.

```bash
# Every ordinary CX Slice
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_current_slice.py \
  --coverage-target services/nex-cx/nex_cx/changed_module.py \
  --smoke scripts/smoke/run_current_slice.py

# Fifth requirement Slice
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_current_requirement_boundary.py \
  --smoke scripts/smoke/run_current_requirement_boundary.py

# Tenth/closure Slice, or immediate fallback at any time
scripts/quality/run_quality_gate.sh
```

`--test`, `--coverage-target`, and `--smoke` are repeatable. Coverage targets
are repository file or directory paths and each explicit target must meet the
Slice thresholds independently. Slice Gate always adds the owning service's
complete regression selection, so focused arguments cannot accidentally
replace service regression. Checkpoint Gate validates each `--test` path but
collects the `tests` directory only once; non-closure focused tests are already
part of that collection, while closure tests remain Full Gate evidence. Both
accelerated tiers run contract validation and fail immediately when any
command fails.

Coverage thresholds:

| Gate | Statement | Branch |
| --- | ---: | ---: |
| Slice/Checkpoint | 95% | 94% |
| Full compatibility gate | 95% | 85% |

The Full Gate thresholds remain backward-compatible. Its observed aggregate
coverage must also be compared with the preceding successful Full Gate;
unexplained coverage reduction is investigated even when the minimum passes.
Reports are written below `reports/quality/` or `reports/coverage/` and are not
committed.

### Escalation Rules

Run Checkpoint or Full Gate earlier than the normal cadence when a Slice changes
shared runtime code, authentication/authorization, the migration runner,
cross-service contracts, multiple services, quality infrastructure, or a
production bootstrap path. PostgreSQL, Playwright, and live-provider smoke
remain explicit protected evidence and must run when the Slice claims those
boundaries.

The rollback path is always the unchanged
`scripts/quality/run_quality_gate.sh`; the tiered runner is not a dependency of
the Full Gate.

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

- The gate required by the cadence and risk level passes.
- The Slice note records the tier, command, result, and elapsed time.
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
