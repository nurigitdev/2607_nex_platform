# Slice 1484: S149 Release-bound Workload Profile

## Outcome

- Added immutable baseline, concurrency, and soak workload profiles.
- Bound every profile to one release candidate and deterministic workload
  digest.
- Declared the complete seven-operation vertical workload mix and per-operation
  timeout.
- Added bounded concurrency, target RPS, warm-up, measurement, cool-down, data
  volume, latency, error, throughput, saturation, duplicate, and isolation
  limits.
- Rejected incomplete, unbounded, non-finite, duplicate, and candidate-mismatch
  profiles before execution.

## Decision

The committed defaults are staging starting points, not production capacity
claims. Slice 1490 must bind any protected run to the exact admitted profile,
and measured evidence may tune the target without introducing model-specific
constants.

## Verification

- Focused unit and runner regression: `41 passed`; new scope statement/branch
  coverage `100%/100%`.
- Platform Slice Gate: `375 passed`, `6 skipped`; new scope statement/branch
  coverage `100%/100%`.
- Contract validation: `174` schemas, `236` positive examples, `204` negative
  examples, and `7` OpenAPI documents.
- Workload smoke: three profiles, seven operations, and `8/8` checks.
- Production deployment remains unapproved.
