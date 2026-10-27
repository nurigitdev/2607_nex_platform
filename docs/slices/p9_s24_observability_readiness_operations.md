# P9-S24: Observability, Readiness, and Operational Projection

## Scope

NeX-WA now exposes an AG-only, signed-service, bounded operational projection:

```text
GET /internal/v1/operations/summary
scope = work:operations:read
```

The projection aggregates fixed-cardinality Job status, oldest runnable age,
ingest outcomes, source conflicts, evidence reuse, stale recovery,
reconciliation completion, and consumer heartbeat state. It never returns or
labels metrics with Job, subject, Artifact, Project, or source identifiers.

WA reuses the Platform `service_operational_events` and `service_log_entries`
schemas in migrations `2606` and `2607`. Intake admission/reuse/conflict,
consumer success/failure/dead-letter, stale recovery, and reconciliation
completion emit bounded metadata only. Consumer outcome logs include
trace/request/Job correlation plus source type, status, and error code, without
raw source content.

API readiness remains migration-backed. Consumer readiness now verifies the
two shared observability tables in addition to queue, heartbeat, evidence, and
asset storage.

## Verification

- fixed-cardinality metric projection and stale-heartbeat calculation
- AG caller/scope protection and unavailable-source behavior
- intake lifecycle events and privacy scan
- migration inventory and consumer storage readiness
- NeX-WA Slice Gate and contract validation

## Evidence

- focused regression: `77 passed`, followed by observability branch additions
- NeX-WA Slice Gate: `262 passed`, `9 skipped`
- statement coverage: `97.13%`
- branch coverage: `94.06%`
- contract validation: `226` schemas, `290` examples, `241` negative
  examples, and `10` OpenAPI documents
- actual `nex_wa_test` migration/bootstrap smoke: `1 passed`
- actual `nex_wa_test` operations storage/projection/zero-residue smoke:
  `1 passed`
