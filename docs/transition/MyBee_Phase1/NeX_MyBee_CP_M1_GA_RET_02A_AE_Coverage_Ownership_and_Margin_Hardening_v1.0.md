# NeX MyBee CP-M1-GA-RET-02A: AE Coverage Ownership and Margin Hardening v1.0

## 1. Status And Authority

- Decision date: `2026-11-16`
- Status: `CLOSED / AS-BUILT / PUBLIC M1 E2E ENTRY ADMITTED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `fdcdb7e88d895cd2f25ece1f13fff2f2ec604575`
- Parent Slice: `CP-M1-GA-RET-02`
- Product behavior change authorized: no
- Database migration authorized: no
- Remote model-provider dependency: none
- Closure date: `2026-11-16`
- Closure evidence:
  `docs/slices/mybee_phase1_w70_cp_m1_ga_ret_02a_ae_coverage_margin.md`

This work order closes the AE Slice Gate ownership and coverage-margin gap
observed immediately after Golden A active binding removal. It does not reopen
the successful Golden A retirement decision, restore a Golden A active import,
or change the installed D04/D12 runtime composition.

The objective is not to increase a percentage by padding tests. The objective
is to ensure that:

1. the AE Gate executes the tests that own behavior included in its coverage
   denominator;
2. active product denial, ambiguity, replay, and malformed-input branches are
   verified;
3. historical quarantine code is visible as historical code rather than
   silently confused with the active runtime; and
4. the AE service has useful margin above its canonical coverage floor before
   the next functional Slice begins.

## 2. Trigger And Measured Baseline

The post-RET-02 AE Slice Gate passed, but branch coverage retained only a
`0.0920` percentage-point margin above the canonical `94.00%` floor.

| Evidence | Statements | Covered | Statement | Branches | Covered | Branch |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `CP-M1-GA-RET-02` | 38,860 | 37,318 | 96.0319% | 12,390 | 11,658 | 94.0920% |
| `CP-M1-E2E-FX-01A.5` | 38,866 | 37,368 | 96.1457% | 12,386 | 11,657 | 94.1143% |
| Earlier AE Slice baseline | 38,011 | 36,560 | 96.1827% | 12,198 | 11,497 | 94.2532% |

The current value is therefore not evidence of a sudden product-code collapse.
It is a small but persistent downward trend combined with an already narrow
branch margin. The corrective Slice is justified because one additional
moderate module can now move the service below the hard floor even when the
new behavior is otherwise correct.

Canonical evidence inputs:

```text
reports/quality/mybee-w70-ga-ret-02-slice-gate.json
reports/quality/mybee-w70-cp-m1-e2e-fx-01a5-ae.coverage.json
reports/quality/slice-nex-ae-api.coverage.json
```

Generated reports remain non-authoritative working evidence. This document
records the durable decision and implementation obligations.

## 3. Source-Backed Findings

### 3.1 The Immediate Statement Delta Is Mostly Historical Quarantine

The RET-02-to-current missing-code delta is concentrated in three modules:

| Module | New missing statements | New missing branches | Initial classification |
| --- | ---: | ---: | --- |
| `mybee_product_consumer.py` | 36 | 0 | Golden A historical-quarantine candidate |
| `project_delegation_planning.py` | 6 | 1 | active installed product code |
| `domain_intent_products.py` | 2 | 2 | Golden A historical-quarantine candidate |

`mybee_product_consumer.py` and `domain_intent_products.py` were intentionally
removed from the active import graph by `CP-M1-GA-RET-02`. Re-importing either
module merely to raise coverage is prohibited.

`project_delegation_planning.py` remains part of the active installed planning
path. Its uncovered denial, ambiguity, authority-resolution, and unsupported
operation branches are genuine product gaps and must be tested.

### 3.2 The AE Test Selector And Coverage Denominator Have Different Ownership

The canonical AE Slice Gate currently selects:

```text
test_nex_ae_*.py
test_ae_*.py
```

while measuring the complete source package:

```text
services/nex-ae-api/nex_ae_api
```

At least seven tests under `tests/mybee_phase1/` import or otherwise verify AE
product and deployment behavior but do not match the AE service patterns.
Relevant examples include the installed MyBee product consumer, runtime
ownership audit, M1 registry bundle locks, foundation admission, and Golden A
retirement contracts.

This is the same class of many-to-many test-ownership problem previously
closed for NeX-EOS by `W40-CA01-S05A`. A filename namespace remains the default
ownership signal, but a narrow explicit mapping is required where one test
owns cross-service or transition behavior.

### 3.3 Absolute Hotspots Must Be Classified Before They Are Changed

The current AE report includes large low-coverage candidates such as:

```text
product_capability_releases.py
product_capability_retirements.py
approval_decision_event_api.py
wa_source_projections.py
p8_demo_controlled_skill.py
eos_outbox_event_api.py
```

Their raw missing-line count does not prove that they should all be added to
this corrective Slice. Each candidate must first be classified as one of:

```text
ACTIVE_PRODUCT
ACTIVE_COMPATIBILITY
HISTORICAL_QUARANTINE
TEST_OR_SMOKE_HARNESS
UNREACHABLE_OR_OBSOLETE_PENDING_RETIREMENT
```

Only active product and active compatibility behavior may be used as the
primary branch-hardening targets. Historical or obsolete code requires a
separate retain, relocate, or retire decision.

## 4. Normative Decisions

### RET-02A-ADR-01: Keep Canonical Floors And Measurement Honest

The existing AE Slice Gate hard floors remain unchanged:

```text
statement >= 95.00%
branch    >= 94.00%
```

This Slice does not authorize a lower threshold, a broad coverage omit, a
wildcard source exclusion, or a reduction in the measured AE source package.

The corrective acceptance targets are:

```text
AE statement >= 96.25%
AE branch    >= 94.50%
```

These are margin targets for this Slice, not new repository-wide hard floors.
If they cannot be reached without synthetic padding or hiding active code, the
Slice must stop and report the remaining ownership/topology decision.

### RET-02A-ADR-02: Add Explicit Many-To-Many Test Ownership

The AE Gate may receive an explicit list or manifest of known AE-owned tests
whose filenames belong to a transition, Platform, or MyBee namespace. The
mapping must be:

- narrow and reviewable;
- protected by a quality-gate unit test;
- deduplicated against the normal filename patterns;
- stable under test-file ordering; and
- limited to tests that exercise code inside the AE coverage target or its
  installed cross-service contract.

Broad patterns such as all `test_w*`, all `tests/mybee_phase1`, or all Platform
tests are prohibited. They would make Slice Gate runtime and ownership
unpredictable.

### RET-02A-ADR-03: Report Active And Historical Ownership Separately

The canonical aggregate AE percentage remains visible. A supplemental
ownership-aware report must classify at least:

```text
active product
active compatibility
historical quarantine
other/unclassified
```

The report must expose file count, statements, missing statements, branches,
missing branches, and ranked hotspots per scope. It must fail closed when a
declared historical module re-enters the active import graph or canonical OCI
composition.

An exact historical module may be removed from the active measurement only by
a separately approved physical relocation or exact hash-pinned coverage-scope
decision. RET-02A does not pre-authorize that removal.

### RET-02A-ADR-04: Harden Active Branches Before Historical Replay Branches

The first product target is `project_delegation_planning.py`. Tests must focus
on behavior such as:

- missing, inactive, ambiguous, or unauthorized Project resolution;
- Project Code and internal Project identity mismatch;
- missing or multiple active Project Agents;
- unsupported or malformed operation/capability identity;
- provider candidate rejection and deterministic fallback boundaries;
- semantic replay mismatch and fail-closed dependency behavior; and
- explicit distinction between clarification, denial, and infrastructure
  failure.

Additional modules may be added only after the ownership inventory identifies
an active installed path and a meaningful uncovered denial, replay, conflict,
or recovery branch.

### RET-02A-ADR-05: Preserve Product And Retirement Semantics

Coverage work must not:

- restore Golden A as an active selector, consumer, activator, rollback
  profile, image input, or prompt dependency;
- change Product Capability Registry or signed Skill semantics;
- add a database migration or public API field;
- change OA, WC, EOS, WA, Project, accounting, or controlled-WRITE authority;
- replace real service behavior with test-only fixture logic; or
- weaken fail-closed runtime behavior to simplify a test.

## 5. Implementation Sequence

### Precondition: CP-M1-GA-RET-02A.0

Before Step 1, the mixed Golden A and generalized runtime import found by the
first ownership scan must be closed. `CP-M1-GA-RET-02A.0` extracts the M1
approval/controlled-WRITE lifecycle into a scenario-neutral module, preserves
the hash-pinned historical modules unchanged, and replaces the prior direct
string check with a recursive import-graph quarantine Guard.

Implementation status: `CLOSED` on `2026-11-16`. The canonical active graph
now reaches `controlled_skill_runtime.py` and reaches none of the five
hash-pinned Golden A source modules. The post-extraction AE Slice Gate passed
at statement `95.8986%` and branch `94.0503%`; these are the starting values
for the ownership and margin work below, not a change to the final targets.

### Step 1: Ownership Inventory And Baseline Tooling

1. Reproduce the RET-02 AE Slice Gate from a clean worktree.
2. Produce a deterministic module inventory with ownership classification.
3. Record the active import graph, canonical OCI inputs, and historical
   quarantine manifest intersection.
4. Add or extend an ownership-aware hotspot report without changing canonical
   coverage thresholds.

### Step 2: AE Test Ownership Reconciliation

1. Audit every `tests/mybee_phase1/` test that imports `nex_ae_api` or asserts
   AE source, runtime, or deployment behavior.
2. Admit only tests with a current AE ownership obligation.
3. Add the narrow mapping to the AE service profile or a shared explicit
   ownership manifest.
4. Add Gate regression proving selection, deduplication, stable ordering, and
   non-selection of unrelated MyBee tests.

### Step 3: Active Runtime Branch Hardening

1. Add focused tests for `project_delegation_planning.py` uncovered branches.
2. Audit the next highest-risk active module from the ownership report.
3. Add tests for denial, replay, conflict, malformed response, and dependency
   failure before adding happy-path duplicates.
4. Refactor only when a narrow responsibility boundary materially improves
   deterministic testing; broad source reorganization is outside this Slice.

### Step 4: Closure Gate

1. Run focused quality-gate tests.
2. Run focused AE ownership and planning regression.
3. Run the canonical AE Slice Gate with statement and branch coverage.
4. Generate aggregate and ownership-aware coverage reports.
5. Run `git diff --check` and record exact test and coverage evidence.

No PostgreSQL, RustFS, remote provider, or browser smoke is required unless an
implementation change unexpectedly crosses one of those runtime boundaries.
If it does, the Slice must stop before making that boundary part of coverage
work.

## 6. Acceptance Criteria

RET-02A may close only when all of the following are true:

1. AE test ownership is explicit and protected by Gate unit tests.
2. No unrelated MyBee, Platform, or transition test is broadly selected.
3. Golden A historical modules remain absent from active imports and canonical
   deployment inputs.
4. Active product and historical-quarantine coverage are separately visible.
5. `project_delegation_planning.py` denial and ambiguity branches are covered
   without changing product semantics.
6. AE statement coverage is at least `96.25%`.
7. AE branch coverage is at least `94.50%`.
8. The canonical hard floors and measured source roots are not weakened.
9. Focused regression, AE Slice Gate, and `git diff --check` pass.
10. A durable Slice record identifies resolved, retained, deferred, and
    historical hotspots.

## 7. Stop Conditions

Implementation must stop and request a decision if:

- an allegedly historical module is imported by the canonical installed
  runtime;
- reaching the target requires a broad omit or source-root reduction;
- the proposed test selector materially increases unrelated service tests;
- an active hotspot requires a product behavior or public contract change;
- a database migration or external live dependency becomes necessary; or
- the targets cannot be met without tests that merely execute lines without
  asserting business behavior.

## 8. Planned Durable Outputs

```text
docs/slices/mybee_phase1_w70_cp_m1_ga_ret_02a_ae_coverage_margin.md
reports/quality/mybee-w70-ga-ret-02a-ae.coverage.json
reports/coverage/mybee-w70-ga-ret-02a-ae-ownership-hotspots.json
```

The `reports/` files are generated evidence and may remain ignored by Git.
The Slice document is the durable As-Built record.

## 9. Non-Goals And Deferred Work

This Slice does not complete the original `CP-M1-E2E-FX-01` public M1 journey.
It does not physically delete Golden A history, redesign all AE test
namespaces, or perform a repository-wide coverage taxonomy migration.

Physical relocation of historical source, retirement of active compatibility
modules, and broader test-ownership normalization require separate decisions
after this narrow margin-hardening Slice closes.

## 10. As-Built Closure

`CP-M1-GA-RET-02A.0` through `.5` are complete. The implementation preserved
the canonical AE source root and hard floors, admitted six exact AE-owned
cross-namespace tests, added the mandatory ownership/quarantine reporter, and
hardened `project_delegation_planning.py` to statement and branch coverage of
`100% / 100%`.

The final canonical AE Slice Gate passed all six commands at aggregate
statement and branch coverage of `96.4497% / 94.6630%`. Active-product
coverage is separately visible at `97.1306% / 94.9836%`; historical coverage
remains unchanged at `86.8421% / 81.7647%`, with zero active-import or
canonical-deployment conflicts. All ten acceptance criteria in Section 6 are
therefore satisfied.

The original `CP-M1-E2E-FX-01` public M1 E2E is admitted to resume. This is an
entry decision only, not public-journey acceptance. The resumed Slice retains
its own actual PostgreSQL, signed trust, live generation, installed runtime,
and Playwright obligations.
