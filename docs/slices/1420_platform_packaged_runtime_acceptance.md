# Slice 1420: Platform Packaged Runtime Acceptance

## Outcome

- Materialized all six owner-scoped OCI build contexts from the canonical
  allowlists and recorded their deterministic context digests.
- Executed each service-owned package-relative migration command against the
  actual OA, MO, CX, AE, and AG test PostgreSQL databases, then verified role,
  database identity, `SELECT 1`, and exact migration head state.
- Executed all seven worker/daemon package-relative entrypoints in `--check`
  mode so PostgreSQL pool readiness was proven without claiming or modifying
  queued work.
- Started OA, MO, CX, AE, AG, and AE Web from their materialized owner contexts,
  verified protected readiness, stopped them in reverse order, and repeated the
  complete six-process generation as restart evidence.
- Added typed evidence that rejects incomplete artifact, migration, background,
  restart, PostgreSQL, rollback, privacy, and production-contact claims.

## OCI Boundary

The host has a Docker CLI, but `/var/run/docker.sock` is owned by `root:docker`,
the current user is not in that group, and passwordless `sudo` is unavailable.
Slice 1420 therefore records `materialized_package_context` execution and
`UNAVAILABLE_PERMISSION_OR_SOCKET`; it does not claim an OCI image build or
container run. This is allowed by the S142 local OCI/package validation
boundary, while actual image execution remains an explicit deployment-host
prerequisite. No registry, remote provider, staging, or production resource was
contacted.

## Verification

- Focused tests: `27 passed`; the new typed acceptance domain has `100%`
  statement and branch coverage.
- Protected smoke: six artifact contexts, five real test PostgreSQL migration
  identities, seven background checks, and two complete HTTP process startup
  generations passed.
- Slice Gate: `995 passed, 11 skipped`; statement coverage `98.44%`; branch
  coverage `97.80%`; contract validation `166` schemas, `228` examples, `196`
  negative examples, and `7` OpenAPI documents.
- The smoke is opt-in through
  `NEX_PLATFORM_PACKAGED_RUNTIME_ACCEPTANCE=1`; the regular quality gate skips
  all protected database activity unless explicitly enabled.
