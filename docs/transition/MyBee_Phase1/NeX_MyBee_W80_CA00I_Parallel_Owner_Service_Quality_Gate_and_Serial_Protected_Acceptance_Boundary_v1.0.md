# NeX MyBee W80-CA00I Parallel Owner-Service Quality Gate and Serial Protected Acceptance Boundary v1.0

**Status:** IN PROGRESS / W80-CA00I.1-.2 COMPLETE

**Predecessor:** W80-CA00H

**Boundary:** parallel owner-service unit/regression/coverage lanes -> isolated
coverage and report artifacts -> exact-once test inventory -> serial cross-service
protected acceptance -> unchanged final repository thresholds

**Database migration:** None. Product database schemas, service database
accounts, and runtime authority contracts are unchanged.

## 1. Purpose

The current Checkpoint and Repository Full Gates preserve strong regression
coverage but take approximately 40 to 50 minutes. The latest measured
Checkpoint Gate completed in `2305.328` seconds. The primary cause is serial
execution: the Checkpoint Gate executes the repository test tree in one pytest
process, while the Full Gate executes the repository pytest/coverage pass and
then hundreds of smoke and evidence commands sequentially.

NeX services already own independent test databases, database accounts,
migrations, and tables. W80-CA00I uses that ownership boundary to parallelize
service-local unit, regression, and coverage work. Cross-service protected
acceptance remains serial so that the final evidence still proves the same
integrated system behavior.

This amendment is a quality-orchestration change. It must not lower coverage
thresholds, skip tests, weaken protected acceptance, or replace the existing
serial Gate until exact equivalence is demonstrated.

## 2. Measured Entry Baseline

The source-backed entry inventory on 2026-11-27 is:

| Signal | Baseline |
| --- | ---: |
| Latest Checkpoint duration | `2305.328s` |
| Repository test files matching `test_*.py` | `1876` |
| Files selected by current service profiles | `1555` |
| Files outside all current service profiles | `321` |
| Files selected by more than one service profile | `77` |
| Full Gate Python smoke/quality/deployment commands after pytest | approximately `798` |
| Available development host capacity | `16 CPU`, `31 GiB RAM` |

The `321` unowned and `77` multi-owned files prohibit replacing the canonical
serial Gate by simply launching the current Slice Gates in parallel. Test
ownership reconciliation is therefore an admission requirement, not optional
cleanup.

## 3. Canonical Decisions

### 3.1 Parallel boundary

Service-local unit, regression, and coverage execution SHOULD run concurrently.
The first admitted lanes are:

1. `nex-ae-api`, started first because it is the current critical path;
2. `nex-eos`;
3. `nex-wc`;
4. `nex-oa`.

Additional owner-service lanes may be admitted after the first four prove
stable. Initial maximum concurrency is four. The limit is configurable but
must not default to an unbounded service count.

### 3.2 Serial boundary

The following remain serial after all owner-service lanes pass:

- tests that intentionally span more than one service authority;
- actual cross-service PostgreSQL protected smoke;
- migration, backup, restart, replay, and zero-residue acceptance that touches
  more than one service database;
- installed Docker Compose and shared-port acceptance;
- authenticated Playwright journeys;
- live-provider acceptance;
- final evidence reconciliation and release decision.

A test is not made parallel merely because its services use separate databases.
If it verifies a cross-service transaction, delivery, authority, or restart
contract, it belongs to the serial integration lane.

### 3.3 Database identity

Each parallel service lane must fail closed before execution unless its admitted
test database and account are distinct from every other active lane. Service
database independence prevents correctness collisions; shared PostgreSQL CPU,
I/O, and connection capacity remain observable performance constraints.

No lane may reset, migrate, or truncate another service's database. A test that
requires that behavior is cross-service and must run serially.

## 4. Exact-Once Test Ownership

The parallel runner must build a canonical repository test inventory before it
starts any lane.

For every collected test file:

- exactly one owner-service lane, or
- exactly one serial `integration/repository` lane

must be selected. Missing ownership, ambiguous ownership without an explicit
resolution, duplicate execution, and inventory drift all fail before pytest.

The inventory receipt records:

- repository revision;
- collected test paths and stable digest;
- assigned lane for every path;
- reason for serial classification;
- missing and duplicate counts, which must both be zero after resolution;
- lane test counts and ownership digest.

Current filename globs remain useful discovery inputs but are not sufficient as
the final authority. Cross-service tests and non-service quality/closure tests
require explicit canonical ownership.

## 5. Coverage and Report Isolation

Every parallel lane writes to a unique run-scoped directory:

```text
reports/quality/parallel/<run-id>/<lane>/
  coverage.json
  junit.xml
  stdout.log
  stderr.log
  evidence.json
```

Raw coverage data also uses a unique `COVERAGE_FILE`, for example:

```text
.coverage.<run-id>.nex-ae-api
.coverage.<run-id>.nex-eos
.coverage.<run-id>.nex-wc
.coverage.<run-id>.nex-oa
```

No parallel process may write the shared `reports/coverage/coverage.json`,
`reports/coverage/junit.xml`, `checkpoint-latest.json`, `slice-latest.json`, or
another lane's evidence.

After all parallel lanes and the serial integration lane pass, the orchestrator
combines the raw coverage data and produces one canonical repository coverage
report. Existing statement and branch thresholds remain unchanged and are
evaluated only against that combined report. Service-local threshold checks are
additional owner-quality evidence, not substitutes for the repository check.

## 6. Gate Execution Model

The admitted execution order is:

```text
SERIAL PREFLIGHT
  -> revision / environment / database identity admission
  -> exact-once test ownership inventory

PARALLEL OWNER-SERVICE PHASE (max 4 initially)
  -> AE API
  -> EOS
  -> WC
  -> OA
  -> later admitted service lanes

SERIAL INTEGRATION PHASE
  -> unowned/reconciled repository tests
  -> cross-service protected PostgreSQL
  -> Compose / restart / Playwright / live-provider acceptance

SERIAL CLOSURE
  -> coverage combine and unchanged thresholds
  -> contract and transition audits
  -> evidence manifest and final Gate decision
```

Failure in preflight prevents all test execution. Parallel lane failures are
reported independently; no protected phase begins unless every required lane
passes. The final Gate is PASS only when the complete inventory, combined
coverage, protected acceptance, and closure all pass.

## 7. Compatibility and Rollback

The current serial commands remain canonical fallback entrypoints throughout
implementation. Parallel execution is enabled explicitly and can be disabled
without a source rollback.

The implementation provides controls equivalent to:

```text
NEX_QUALITY_GATE_EXECUTION=serial|parallel
NEX_QUALITY_GATE_MAX_PARALLEL=4
```

`serial` must preserve the current behavior. Until parity is proven, CI and
release evidence may run both modes and compare collected tests, result status,
coverage totals, and protected evidence. A mismatch fails closed and retains
the serial result as authority.

## 8. Implementation Slices

### W80-CA00I.1 - Timing and Exact-Once Ownership Inventory

- add per-command and per-phase timing evidence;
- reconcile all test files to one owner or the serial integration lane;
- add missing, duplicate, and inventory-drift guards.

**As-Built:** COMPLETE. Checkpoint and Full inventories assign every discovered
test exactly once. The entry profile ambiguity is retained as an observable
source signal, while resolved missing and duplicate counts are both zero.

### W80-CA00I.2 - Run-Scoped Coverage and Report Isolation

- isolate raw coverage, JSON coverage, JUnit, logs, and lane evidence;
- add collision tests for concurrent writers;
- preserve current service coverage ownership reports.

**As-Built:** COMPLETE. Every lane now receives an isolated run-scoped raw
coverage file, JSON report, JUnit report, stdout/stderr log, and evidence file.
Duplicate lane claims and any artifact-path collision fail before test execution.

### W80-CA00I.3 - Bounded Parallel Owner-Service Orchestrator

- start AE first and execute admitted owner lanes with bounded concurrency;
- collect every lane result and duration;
- retain an explicit serial fallback and fail-closed cancellation behavior.

### W80-CA00I.4 - Checkpoint Gate Parallel Admission

- compare serial and parallel test inventory and results on the same revision;
- combine coverage and apply unchanged thresholds;
- admit parallel Checkpoint only after parity and timing evidence pass.

### W80-CA00I.5 - Repository Full Gate and Protected Serial Closure

- retain cross-service protected acceptance as a serial phase;
- classify Full Gate smoke commands by owner and mutation boundary;
- prove report isolation, no DB collision, exact coverage parity, and serial
  rollback;
- record before/after duration and final As-Built evidence.

## 9. Acceptance Criteria

| Case | Required result |
| --- | --- |
| Owner-service tests run together | Distinct DB identities and report paths; no collision |
| One test matches two service profiles | Explicitly resolved or serially classified before execution |
| One test matches no profile | Explicit repository/integration ownership; never silently skipped |
| Lane fails | Protected phase does not start; lane-specific diagnostics remain available |
| All lanes pass | Raw coverage combines into one canonical report |
| Combined coverage | Existing statement and branch thresholds pass unchanged |
| Cross-service PostgreSQL test | Runs only in the serial protected phase |
| Playwright/live-provider acceptance | Runs serially after owner lanes |
| Parallel/serial parity | Same canonical inventory and equivalent PASS/FAIL result |
| Parallel execution disabled | Existing serial Gate remains runnable without source rollback |

The target is to reduce Checkpoint wall time from approximately 38 to 40 minutes
to an initial 22 to 28 minutes, and Repository Full Gate wall time from
approximately 40 to 50 minutes to an initial 28 to 35 minutes. These are
engineering targets, not pass criteria; regression completeness and evidence
integrity take precedence over elapsed time.

## 10. Non-Goals

W80-CA00I does not:

- lower statement or branch coverage thresholds;
- skip slow, protected, browser, PostgreSQL, or live tests;
- create shared product tables or change service database ownership;
- run cross-service mutation journeys concurrently;
- introduce unbounded pytest or smoke concurrency;
- infer test ownership only from a convenient filename when authority is
  ambiguous;
- replace the serial Gate before parity evidence passes;
- change product behavior, service APIs, migrations, or runtime deployment.

## 11. Stop Conditions

Implementation stops for a decision if:

- complete exact-once ownership cannot be established;
- combined coverage cannot reproduce the serial Gate totals within an explained
  tool-level tolerance;
- a service test mutates another service database;
- parallel execution causes nondeterministic test or evidence results;
- report isolation requires changing product-owned evidence semantics;
- PostgreSQL, Docker, port, browser, or provider contention makes the protected
  phase unreliable;
- serial fallback cannot reproduce the current canonical Gate.

## 12. Closure Contract

```text
OWNER-SERVICE UNIT/REGRESSION/COVERAGE       = PARALLEL
CROSS-SERVICE PROTECTED ACCEPTANCE           = SERIAL
INITIAL MAXIMUM PARALLEL LANES                = 4
AE LANE START ORDER                           = FIRST
TEST FILE OWNERSHIP                           = EXACTLY ONCE
MISSING OR AMBIGUOUS OWNERSHIP                = FAIL CLOSED
COVERAGE/REPORT PATHS                         = RUN- AND LANE-SCOPED
FINAL COVERAGE                                = COMBINED REPOSITORY REPORT
STATEMENT/BRANCH THRESHOLDS                   = UNCHANGED
SERIAL FALLBACK                               = REQUIRED
PRODUCT DATABASE/API/MIGRATION CHANGE         = NONE
```

W80-CA00I closes only after parallel Checkpoint and Repository Full Gate runs
prove complete test inventory, isolated artifacts, unchanged coverage and
protected acceptance, deterministic results, a working serial fallback, and a
measured wall-time reduction on the same repository revision.
