# Slice 1326: Platform PostgreSQL pool lifecycle

## Outcome

- Added separate API and worker engines and session factories for each of the
  five service-owned test databases.
- Required both engine and session query readiness before the lifecycle reaches
  `READY`.
- Added reverse-order, deduplicated, retryable disposal and fail-safe cleanup
  for partial initialization.
- Added protected evidence that disposes ten pools and then creates ten fresh
  pools from a new lifecycle.

## Decision

Restart never reuses a prior engine or session factory. API and worker
workloads retain independent pool settings, and any partial construction or
shutdown failure is normalized without exposing database URLs or exceptions.

## Verification

- Focused regression: `7 passed`, `1 protected skip`; exact statement/branch
  coverage: `100%/100%` for pool lifecycle and smoke runner.
- Protected actual PostgreSQL regression: `8 passed` with no skip; `5`
  services, `10` API/worker pools, `10` fresh engines after rebuild, and `20`
  total pool disposals passed.
- Slice Gate: `941 passed`, `12 skipped`; aggregate statement coverage `98.45%`
  and branch coverage `97.75%`.
- Checkpoint Gate: `10,478 passed`, `26 skipped`; aggregate statement coverage
  `98.91%` and branch coverage `97.25%`.
- Every explicit S133 Checkpoint script scope reached `100%/100%`; the new
  shared pool lifecycle also reached `100%/100%` in the combined report.
- Contract validation: `156` schemas, `214` examples, `184` negative examples,
  and `7` OpenAPI documents passed.
