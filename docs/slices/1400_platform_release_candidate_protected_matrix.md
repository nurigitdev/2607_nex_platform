# Slice 1400: Platform Release-Candidate Protected Matrix

## Outcome

- Added one protected orchestrator that runs S140 admission, ten deterministic
  golden scenarios, five-database restart, live provider/calibration/grounded
  generation, Korean browser plus AG operations, and assurance evidence.
- Aggregated the eight non-regression RC gates with exact inventory, freshness,
  digest, privacy, metric, and protected-execution validation.
- Left `full_regression` as an explicit `SKIPPED` placeholder. Slice 1400
  succeeds only when the evaluator is blocked by that one gate and every other
  gate passes. It cannot declare a release candidate before Slice 1401.
- Isolated source-specific runtime profiles. S140 admission remains
  `SIGNED_ONLY/live`; S133 restart executes its canonical `test/mock` provider
  profile; S138/S139 in-process trace sources execute their documented
  `TEST_MOCK` service-token profile and restore process environment afterward.
- Kept the combined evidence metadata-only and retained
  `production_deployment_approved=false`.

## Fail-Closed Diagnosis

The first combined runs correctly failed with `6/8` non-regression gates.
Diagnosis showed two source-profile collisions:

- S133 `test` runtime startup received the admission `live` provider mode,
  conflicting with its canonical `mock` provider profile.
- S138 creates mock service tokens in-process, while service-auth construction
  read `SIGNED_ONLY` from process environment and marked four source APIs
  unavailable.

No gate was weakened and no automatic retry was added. The orchestrator now
passes each source its own already-tested profile and restores global state.

## Protected Verification

The complete runner was executed with
`NEX_S140_RELEASE_CANDIDATE_PROTECTED_MATRIX=1`, admitted signed/live modes,
all five test database URLs, and the three provider configurations supplied
outside source control.

Observed result:

- non-regression RC gates: `8/8`
- protected gates with actual execution: `5/5`
- privacy violations: `0`
- pending gate: `full_regression` only
- provisional decision: `READY_FOR_FULL_GATE`
- release-candidate decision: still `BLOCKED`
- next Slice: `1401`

## Quality Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_runtime_release_candidate_protected_matrix.py \
  --coverage-target services/_shared/nex_runtime/release_candidate_protected_matrix.py \
  --coverage-target scripts/smoke/run_platform_release_candidate_protected_matrix.py \
  --smoke scripts/smoke/run_platform_release_candidate_protected_matrix.py
```

Slice 1401 owns the fresh Full Gate evidence, final nine-gate evaluation,
operator runbook, and S140 closure.

Observed Slice Gate:

- `982 passed`, `11 skipped`
- statement coverage: `98.47%`
- branch coverage: `97.82%`
- both new files: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` positive examples, `196`
  negative examples, `7` OpenAPI documents
