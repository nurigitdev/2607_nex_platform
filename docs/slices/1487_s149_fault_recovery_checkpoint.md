# Slice 1487: S149 Fault, Provider Degradation, and Recovery Checkpoint

## Outcome

- Added eight allowlisted, release-bound fault scenarios covering five fault
  classes.
- Added explicit `PLANNED -> INJECTING -> DEGRADED -> RECOVERING -> RECOVERED`
  transitions and terminal failure handling.
- Restricted provider faults to client timeout, 5xx, and latency injection;
  DGX process mutation remains prohibited.
- Added detection and recovery budgets plus mandatory zero data loss,
  isolation violation, and residue checks.
- Preserved same-host restart semantics without claiming distributed failover.

## Decision

Protected fault injection remains explicit opt-in and staging-only. Slice 1490
may execute only the admitted plan and must restore every local route or
service before cleanup completes.

## Verification

- Focused fault/recovery regression: `33 passed`; new scope statement/branch
  coverage `100%/100%`.
- Platform Slice Gate: `367 passed`, `6 skipped`; new scope statement/branch
  coverage `100%/100%`.
- Fault/recovery smoke: eight scenarios, five classes, eight recovered, zero
  residue, and `12/12` checks.
- Fifth-Slice Checkpoint Gate: `12,715 passed`, `32 skipped`; statement
  coverage `98.96%`, branch coverage `97.49%`; all nine S149 coverage scopes
  `100%/100%` and all five registered S149 smoke runners passed.
- Contract validation: `174` schemas, `236` positive examples, `204` negative
  examples, and `7` OpenAPI documents.
- Production deployment remains unapproved.
