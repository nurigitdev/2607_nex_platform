# Slice 1473: S148 Observability and Incident Boundary

## Outcome

- Froze metadata-only metric, log, trace, and readiness signal correlation.
- Defined service-owned SLI/SLO evaluation with explicit `NO_DATA` behavior.
- Separated alert lifecycle from restart-safe notification delivery.
- Defined `local_only`, `private_network`, and `internet_connected` modes under
  one provider-neutral delivery contract.
- Recorded that current external acceptance is mock-only and must report
  `EXTERNAL_NOT_ACTIVATED`.
- Preserved AG ownership without reusing the operator-review-specific dispatch
  table as the platform alert source of record.
- Recorded the single-host total-outage detection limitation.

## Decision

S148 will use concise AG-owned alert and notification outbox tables, reuse the
existing bounded dispatch patterns, and expose one protected AG operations
projection. No third-party endpoint or production resource is contacted by
this Slice.

## Verification

- Focused boundary regression: `4 passed`.
- AG Slice Gate: `2,478 passed`; statement coverage `98.88%`, branch coverage
  `96.48%`.
- Slice 1473 coverage scope: statement `100.00%`, branch `100.00%`.
- Contract validation: `168` schemas, `230` examples, `198` negative examples,
  and `7` OpenAPI documents.
- Boundary audit: `12/12` checks, three delivery modes, five service owners,
  seven gaps, ten Slices, and `next=1474`.
