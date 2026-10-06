# Slice 1401: S140 Platform Release-Candidate Closure

## Outcome

- Added a typed closure adapter that replaces the single Slice 1400
  `full_regression` placeholder with fresh pytest JUnit and coverage evidence.
- Re-evaluated the unchanged nine-gate release-candidate matrix. Closure
  requires `9/9` gates, all five protected gates with actual execution, zero
  privacy violations, and `production_deployment_approved=false`.
- Added fail-closed parsing for malformed JUnit, inconsistent test counts,
  malformed coverage totals, coverage below the existing `95%` statement or
  `85%` branch thresholds, missing protected evidence, and stale or failed
  matrix records.
- Added atomic metadata-only evidence output for the protected matrix and final
  closure under operator-selected ignored paths.
- Registered Slice 1397 through Slice 1401 runners exactly once in Full Gate.
  Protected execution remains opt-in; ordinary deterministic Full Gate runs do
  not contact databases, providers, or browsers through these runners.
- Published the S140 operator runbook with admission, execution, triage,
  cleanup, fail-closed, and production-deferral guidance.

## Protected And Full-Gate Evidence

- Protected matrix: `8/8` non-regression gates passed, all `5/5` protected
  gates were actual executions, one `full_regression` gate remained pending,
  and privacy violations were `0`.
- Full Gate: `12,010 passed`, `31 skipped`, zero failures/errors, statement
  coverage `98.11%`, branch coverage `97.01%`, and contract validation
  `166` schemas / `228` examples / `196` negative examples / `7` OpenAPI
  documents.
- Final closure: `9/9` gates passed, all `5/5` protected gates retained actual
  execution, privacy violations remained `0`, and the decision was
  `RELEASE_CANDIDATE` with `production_deployment_approved=false`.

Runtime evidence remains outside source control.

The first Full Gate attempt correctly stopped at one stale S131 closure
expectation: its dynamic inventory observed all ten named golden scenarios,
while the historical closure still required the pre-S140 value of zero. The
closure now requires the exact resolved inventory of ten; no release gate,
coverage threshold, or protected-execution requirement was relaxed.

The next Full Gate completed its tests and quality checks but the new closure
adapter failed closed because pytest places aggregate counts on a child
`testsuite` when the root is `testsuites`. The parser now supports both
root-aggregate and child-suite JUnit forms, has a dedicated regression test,
and the complete Full Gate was rerun successfully from the beginning.

## Release Decision

S140 declares `RELEASE_CANDIDATE` from the accepted closure summary of nine
passing gates, five actual protected gates, no failed regression test, and zero
privacy violations. This decision does not approve production deployment.
