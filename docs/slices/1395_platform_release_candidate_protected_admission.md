# Slice 1395: Platform Release-Candidate Protected Admission

## Outcome

- Added a fail-closed S140 admission profile that requires exactly five
  service-local PostgreSQL test targets, three live provider capabilities, and
  the desktop/mobile browser viewport inventory.
- Reused the canonical PostgreSQL target resolver, including expected database
  names, owner roles, PostgreSQL driver checks, and service-local URL guards.
- Required PostgreSQL persistence, live provider mode, signed service trust,
  OA-backed AE sessions, and API-only AG operations projection.
- Required the canonical OpenAI-compatible provider profile and rejected the
  legacy PCX profile for release-candidate execution.
- Kept provider admission model-independent. It binds capability aliases and
  configured endpoint environment names, while model identity and confidence
  calibration are verified during protected live execution.
- Projected no database URL, endpoint value, credential, token, or secret.
- Performed no database connection, remote provider request, or browser launch.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_runtime_release_candidate_admission.py \
  --coverage-target services/_shared/nex_runtime/release_candidate_admission.py \
  --coverage-target scripts/smoke/run_platform_release_candidate_admission.py \
  --smoke scripts/smoke/run_platform_release_candidate_admission.py
```

The deterministic contract sample must report `databases=5`, `providers=3`,
`viewports=2`, and `next=1396`. Actual protected commands must omit `--sample`
and use `--environment` with values provided outside source control.

Observed result:

- `992 passed`, `11 skipped`
- statement coverage: `98.47%` (threshold `95.00%`)
- branch coverage: `97.82%` (threshold `94.00%`)
- protected admission module: statement `100.00%`, branch `100.00%`
- admission runner: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` positive examples, `196`
  negative examples, `7` OpenAPI documents
- contract sample: five databases, three provider capabilities, two
  viewports, next Slice `1396`

The eleven skipped PostgreSQL tests are expected in the deterministic Slice
Gate. Admission is configuration proof, not protected execution evidence.
