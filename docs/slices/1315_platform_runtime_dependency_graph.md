# Slice 1315: Platform runtime dependency graph

## Outcome

- Added deterministic topological startup layers and dependency probe targets.
- Rejected empty, unknown, cyclic, and non-probeable dependency graphs.
- Selected liveness probes for database-free `local_mock` startup and readiness
  probes for protected profiles.
- Published only process ids, probe modes, URLs, and bounded timeout metadata.

## Verification

- Focused regression: `9 passed`.
- Slice Gate: `943 passed`, `11 skipped`.
- Aggregate coverage: `98.43%` statement, `97.73%` branch.
- Changed graph and evidence modules: `100.00%` statement and branch.
- Contract validation: `156` schemas, `214` positive examples, `184`
  negative examples, and `7` OpenAPI documents.
- Graph evidence: three startup layers, two dependency probes, local liveness,
  and protected readiness selection.
