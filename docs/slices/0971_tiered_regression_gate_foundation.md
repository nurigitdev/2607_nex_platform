# Slice 0971: Tiered Regression Gate Foundation

## Goal

Reduce ordinary Slice verification time without abandoning service-wide
regression, branch coverage, contract validation, requirement checkpoints, or
the original complete quality gate.

## Baseline

Before this Slice, the Full Gate collected `7,493` tests and its pytest plus
coverage phase required `688.79` seconds. It then started `343` Python smoke
processes and one Node smoke process, including historical closure summaries
and protected runners that normally report `SKIPPED`.

## Implementation

- Preserved `scripts/quality/run_quality_gate.sh` as an unchanged, independent
  Full Gate and immediate rollback path.
- Added a Slice Gate that automatically selects all tests owned by one service,
  merges repeatable focused tests without duplication, measures the service and
  explicitly changed modules, validates contracts, and runs only explicitly
  selected smoke evidence.
- Added a fifth-Slice Checkpoint Gate that runs platform regression while
  excluding historical `test_s*_closure.py` files, measures all service and
  provider source, validates contracts, and accepts current-boundary smoke.
- Kept Checkpoint focused-test arguments as validation hints rather than
  duplicate pytest collection paths. Passing `tests` and child files together
  caused pytest to collect only the child files in this repository; a
  regression test now protects the full-directory selection.
- Raised accelerated-tier branch coverage to `94%`; statement remains `95%`.
- Enforced the same thresholds independently for every explicitly changed
  coverage file or directory so service-wide coverage cannot hide a new gap.
- Restricted focused tests, smoke scripts, coverage paths, and report paths to
  repository-owned boundaries.
- Added fail-fast command execution, non-secret local evidence under
  `reports/quality/`, elapsed-time reporting, and dry-run planning.
- Added risk escalation for shared runtime, auth, migrations, cross-service or
  multi-service changes, production bootstrap, quality infrastructure, and
  release boundaries.

## Cadence

1. Every Slice: Slice Gate, focused evidence, `git diff --check`, commit, push.
2. Fifth Slice in the active requirement: Checkpoint Gate.
3. Tenth/closure Slice: existing Full Gate and required protected smoke.
4. Any Slice: escalate immediately when its blast radius requires it.

The positions are relative to the active requirement and are not inferred from
the final digit of a repository Slice number. S98 feature work starts after
this process-only Slice.

## Commands

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_current_slice.py \
  --coverage-target services/nex-cx/nex_cx/changed_module.py \
  --smoke scripts/smoke/run_current_slice.py

scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_current_requirement_boundary.py \
  --smoke scripts/smoke/run_current_requirement_boundary.py

# Full fallback and closure gate
scripts/quality/run_quality_gate.sh
```

## Verification

- Focused quality-runner regression: `22 passed` in `0.35s`; both new quality
  modules reached statement and branch coverage `100%`.
- Slice Gate (`nex-cx`): `1,960 passed` from `130` selected test files;
  statement `98.88%`, branch `97.83%`, all `5/5` commands, contracts and S97
  closure smoke passed, total `79.505s`.
- Checkpoint Gate: `7,134 passed` in `418.79s`; statement `98.59%`, branch
  `96.38%`, contracts and S97 closure smoke passed, total `428.767s`.
- Existing Full Gate: `7,515 passed` in `698.93s`; statement `98.89%`, branch
  `96.63%`, contracts and the complete historical smoke matrix completed with
  exit code `0`.
- Failure-detection check: the first Checkpoint trial completed in `3.696s`
  with only `21` tests, which exposed the duplicate pytest collection-path
  issue. The run was rejected, the selector was corrected, and the measured
  `7,134`-test Checkpoint above is the accepted evidence.

The Full Gate script was not changed and remains directly runnable without the
tiered runner, so returning to the previous regression policy requires no code
or configuration change.
