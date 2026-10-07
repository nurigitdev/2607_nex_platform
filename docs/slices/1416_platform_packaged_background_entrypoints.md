# Slice 1416: Packaged Background Entrypoints

## Outcome

- Moved the canonical seven-role background process shell from `scripts/dev`
  into the owner artifacts through `nex_runtime.background_process`.
- Retained the source command as a thin compatibility wrapper and removed
  repository `.py` and `.mjs` paths from all thirteen packaged commands.
- Aligned protected test workers with `NEX_AE_TEST_DATABASE_URL`,
  `NEX_CX_TEST_DATABASE_URL`, and `NEX_AG_TEST_DATABASE_URL` instead of the
  development database variable names.
- Executed every background `--check` from its materialized owner-scoped OCI
  context, proving that no sibling service source is required.

## Capability Decision

Entrypoint parity and work-execution parity are different controls. CX
ingestion has a durable job-claiming process adapter. The other six packaged
background roles currently provide lifecycle and import readiness but do not
claim work through the shared process shell. They are explicitly classified as
`lifecycle_only`; staging and production background admission remains closed.

This is intentionally fail-closed. S142 does not represent a passive process
as an operational worker or silently enable production. Owner-specific worker
adapters require separate implementation and protected evidence before that
admission can change.

## Verification

- Focused tests: `40 passed`; background process, packaged entrypoint domain,
  and packaged entrypoint smoke runner statement and branch coverage are all
  `100%`.
- Packaged context smoke: `13` entrypoints, `7` background checks executed,
  `1` job-claiming role, `6` lifecycle-only roles, and `0` source-tree
  commands; no database or provider was contacted.
- Slice Gate: `994 passed, 11 skipped`; statement coverage `98.51%`; branch
  coverage `97.90%`; contract validation `166` schemas, `228` examples, `196`
  negative examples, and `7` OpenAPI documents.
- Fifth-Slice Checkpoint Gate: `11,467 passed, 30 skipped`; statement coverage
  `98.93%`; branch coverage `97.33%`; all `8/8` commands passed and the three
  new coverage scopes remained at `100%` statement and branch coverage.
- The first checkpoint run exposed one S135 repository audit that still read
  only the former source wrapper. The audit now checks the canonical packaged
  module plus wrapper delegation; its focused regression and the repeated
  complete Checkpoint Gate both pass.
