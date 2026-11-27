# W80-CA00I.2 Run-Scoped Coverage and Report Isolation

## Outcome

- Added a canonical `LaneArtifactPaths` layout under
  `reports/quality/parallel/<run-id>/<lane>/`.
- Isolated raw coverage, JSON coverage, JUnit, stdout, stderr, and lane evidence.
- Set lane-local `COVERAGE_FILE`, run identity, and lane identity in the child
  process environment.
- Added safe run/lane identifier admission and rejected unknown service lanes.
- Added an atomic directory claim so two writers cannot share one lane output.
- Added cross-lane collision validation before concurrent execution.

## Canonical Layout

```text
reports/quality/parallel/<run-id>/<lane>/
  .coverage
  coverage.json
  junit.xml
  stdout.log
  stderr.log
  evidence.json
```

The established `reports/coverage/coverage.json`, `junit.xml`, and tier-level
`*-latest.json` files are not written by parallel lanes. Final publication is a
later orchestrator responsibility after all lanes and coverage combination pass.

## Verification

```text
37 focused tests passed
parallel quality module statement/branch coverage = 100%
different owner lanes have disjoint artifact paths = PASS
duplicate run/lane claim = DENIED
synthetic artifact path collision = DENIED
unsafe run identity and unknown lane = DENIED
```

No database, API, migration, threshold, runtime deployment, or existing serial
Gate behavior changed. W80-CA00I.3 may now execute owner-service lanes
concurrently without sharing coverage or report files.
