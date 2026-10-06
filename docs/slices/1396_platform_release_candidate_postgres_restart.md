# Slice 1396: Platform Release-Candidate PostgreSQL Restart Evidence

## Outcome

- Reused the protected S133 restart orchestrator rather than creating a second
  migration, process, pool, or restoration implementation.
- Added an S140 adapter that converts the protected run into the typed
  `five_database_restart` release-candidate gate evidence.
- Required all five service-owned test databases, two migration gates, two
  thirteen-process runtime generations, fresh connection pools, one restart,
  five restored sentinels, five cleaned sentinels, and confirmed absence in
  all five databases.
- Kept work claiming disabled and required no remote model provider for this
  database-only release gate.
- Projected only bounded counts, statuses, checks, timestamps, and a digest.
  Database URLs, credentials, payloads, and private values are excluded.
- Hardened Checkpoint coverage planning so `services` and `providers` are
  measured once while explicit files below those roots remain independent
  threshold scopes. This prevents overlapping pytest-cov sources from causing
  duplicate module collection.
- Updated the S131 repository audits to recognize that all ten named golden
  scenarios became executable in Slice 1394.

## Protected Verification

The protected runner was executed with `NEX_S140_RELEASE_CANDIDATE_POSTGRES_RESTART=1`
and the five service-local `NEX_*_TEST_DATABASE_URL` values supplied outside
source control.

Observed result:

- actual PostgreSQL execution: `PASS`
- databases reached/restored/cleaned/confirmed absent: `5/5/5/5`
- process topology: `13` processes across `2` fresh generations
- migration gates: `2`
- restart count: `1`
- database residue: `0`
- next Slice: `1397`

The normal Slice and Checkpoint gates invoke the protected runner without the
enable flag and therefore report `SKIPPED`. That deterministic skip is not the
protected release evidence recorded above.

## Quality Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_runtime_release_candidate_postgres.py \
  --coverage-target services/_shared/nex_runtime/release_candidate_postgres.py \
  --coverage-target scripts/smoke/run_platform_release_candidate_postgres_restart.py \
  --smoke scripts/smoke/run_platform_release_candidate_postgres_restart.py

scripts/quality/run_checkpoint_gate.sh \
  --coverage-target services/_shared/nex_runtime/release_candidate_postgres.py \
  --coverage-target scripts/smoke/run_platform_release_candidate_postgres_restart.py \
  --smoke scripts/smoke/run_platform_release_candidate_postgres_restart.py
```

Observed Slice Gate:

- `990 passed`, `11 skipped`
- statement coverage: `98.46%`
- branch coverage: `97.81%`
- both new files: statement `100.00%`, branch `100.00%`

Observed fifth-Slice Checkpoint Gate:

- `11,270 passed`, `30 skipped`
- statement coverage: `98.91%`
- branch coverage: `97.29%`
- both new files: statement `100.00%`, branch `100.00%`
- contract validation: `166` schemas, `228` positive examples, `196`
  negative examples, `7` OpenAPI documents

Slice 1397 can now execute the model-independent live embedding, reranking,
generation, calibration, and grounded-provider gate.
