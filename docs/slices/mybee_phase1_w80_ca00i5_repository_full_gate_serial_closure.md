# W80-CA00I.5 Repository Full Gate and Protected Serial Closure

## Result

`COMPLETE` with a fail-closed admission decision:

- the parallel Checkpoint Gate remains admitted with four owner lanes;
- the Repository Full Gate remains canonical serial;
- the diagnostic parallel Full test phase is not a release entrypoint;
- cross-service protected acceptance remains serial and unchanged.

No product API, database migration, authority contract, or runtime deployment
was changed.

## Same-Revision Evidence

| Measurement | Parallel Full test-phase experiment | Canonical serial Full Gate |
| --- | ---: | ---: |
| Repository test files | `1877` | `1877` |
| Python tests | complete inventory | `24344 passed`, `199 skipped` |
| Test-phase duration | `3676.517s` | `3318.71s` |
| Statement coverage | `96.11%` | `96.11%` |
| Branch coverage | `94.91%` | `94.91%` |
| Product statement / branch | `98.09% / 96.48%` | `98.09% / 96.48%` |
| Harness statement / branch | `93.59% / 91.64%` | `93.59% / 91.64%` |
| Complete Gate duration | not admitted | `4200s` |
| Result | performance rejection | `PASS` |

The parallel experiment preserved correctness and coverage, but was
`357.807s` slower than the serial pytest/coverage phase. It also delayed the
protected and repository closure phases, so execution was stopped before those
unchanged serial phases and the canonical Full Gate was run from the beginning.

## Decision

The Full Gate shell accepts `NEX_QUALITY_GATE_EXECUTION=serial`. A `parallel`
request fails before pytest with an explicit non-admission diagnostic. This
prevents a slower experimental mode from being mistaken for release evidence.

The standalone `run_parallel_quality_gate.py full-test-phase` command is kept
for reproducibility and further profiling. Its run-scoped lane coverage, JUnit,
logs, exact-once inventory, and merge guards remain tested, but its output is
diagnostic evidence only.

## Why More Or Fewer Lanes Did Not Help

- Four Checkpoint owner lanes completed in `1115.075s`.
- Three Checkpoint owner lanes completed in `1237.235s`, `122.160s` slower.
- Full Gate still has `322` repository and historical closure files outside the
  owner lanes.
- Every Full owner lane measures the complete source tree, adding substantial
  fixed coverage startup and reporting cost.

The next optimization boundary is therefore ownership and coverage structure,
not a lane-count change: classify the remaining repository tests, separate
historical closure validation where safe, and avoid repeated whole-source
coverage measurement while preserving exact combined coverage.

## Verification

- focused Python tests for the parallel orchestrator and gate wrappers: PASS;
- shell syntax and invalid-mode fail-closed checks: PASS;
- four-lane Checkpoint Gate: PASS;
- controlled three-lane Checkpoint owner comparison: PASS, slower;
- four-lane Full test-phase experiment: correctness PASS, performance FAIL;
- canonical serial Repository Full Gate: PASS in `4200s`;
- final statement/branch thresholds: `96.11% / 94.91%`, unchanged.
