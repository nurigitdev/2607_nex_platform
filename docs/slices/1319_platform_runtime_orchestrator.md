# Slice 1319: Platform runtime orchestrator

## Outcome

- Added a manifest-driven orchestrator that launches one dependency layer at
  a time and does not advance until every process in the layer is ready.
- Local mock API and Web processes use liveness probes; protected profiles use
  readiness probes. Background processes require repeated survival checks.
- Added bounded startup, normalized failure states, reverse-order cleanup,
  graceful termination, and forced-kill fallback.
- Added a machine-readable status projection that excludes commands,
  environment values, process IDs, and raw exception details.
- Kept `scripts/dev/run_all_services.py` unchanged as the rollback runner.

## Decision

Process launching and HTTP probing are adapter boundaries. Deterministic tests
exercise ordering, retries, timeout, early exit, launch failure, cleanup, and
redaction without starting local services. Slice 1320 will run the same domain
with the subprocess and HTTP adapters against all thirteen local mock
processes.

## Verification

- Focused regression: `22 passed`.
- Orchestrator scope: statement `100.00%`, branch `100.00%`.
- Slice Gate (`nex-oa`): `957 passed`, `11 skipped`; statement `98.41%`,
  branch `97.71%`.
- Simulated complete topology: `13` ready, `13` stopped, reverse shutdown
  order verified, and safe status projection verified.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- The diagnostic `nex-runtime` profile ran `503` passing tests but its legacy
  test-selection/coverage-target mismatch produced `92.66%` statement and
  `88.56%` branch aggregate coverage. The established `nex-oa` Slice Gate and
  exact changed-scope checks are the authoritative result for this Slice.
- No PostgreSQL database or remote provider is contacted.
