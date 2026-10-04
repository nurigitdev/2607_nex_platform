# Slice 1309: Platform persistence, worker, and process audit

## Outcome

- Confirmed all five backend services attach the shared service-local
  persistence runtime and expose the same authenticated local JobQueue control
  surface.
- Confirmed the repository has 89 service-owned SQL migrations and one runner
  that supports `--all` plus the protected `test` database profile.
- Confirmed PostgreSQL runtime wiring builds separate API and worker engines,
  pools, and session factories.
- Identified seven concrete worker/daemon runtime modules, but only two expose
  their own executable `main` path. Existing focused restart smokes are useful
  component evidence rather than a coordinated platform restart proof.
- Identified a P0 process-orchestration gap: `run_all_services.py` launches the
  five backend API shells, but does not run migrations, wait for readiness,
  launch AE Web or workers/daemons, or apply an automatic restart policy.

## Decision

Service-local databases and distinct API/worker pools remain canonical. The
current all-services development runner is not promoted to release
orchestration by documentation alone. S132 must define a typed process and
configuration manifest. S133 must use it to coordinate test migrations,
readiness, ordered shutdown/restart, and durable reload evidence across all
five service databases.

No database or remote provider mutation is required for this repository audit
Slice.

## Verification

- Focused tests: `4 passed`.
- Slice Gate (`nex-oa`): `938 passed`, `11 skipped`.
- Coverage: statement `98.42%`, branch `97.71%`.
- Changed audit runner coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Audit summary: 5 backend services, 89 migrations, 7 worker/daemon runtime
  modules, 2 directly executable runtime modules, and all 5 process-level
  orchestration capabilities absent from the current aggregate runner.
