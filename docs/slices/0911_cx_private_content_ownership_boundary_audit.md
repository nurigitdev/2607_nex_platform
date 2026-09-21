# Slice 0911: CX private content and ownership persistence boundary audit

## Goal

Freeze the S92 implementation boundary before changing CX runtime or storage.

## Findings

- Source text, chunk text, chunk vectors, summary text, and summary vectors are
  currently held by the broad process-local `ContentIngestionStore`.
- Public PostgreSQL already stores hashes, dimensions, URIs, and ownership
  metadata instead of private payload values.
- Source bytes already have a durable filesystem boundary; four derived private
  payload classes still require explicit adapters.
- Owner lineage must extend beyond content objects to jobs, processing runs,
  retrieval packages, and generation execution state.
- Import-time singleton mutation must be removed as runtime dependencies are
  introduced.

## Decision

Public PostgreSQL remains metadata-only. S92 introduces `CxAccessContext`,
central authorization, private text/vector capability ports, owner-scoped local
filesystem adapters, and owner lineage persistence in small slices.

The current versioned SQL ledger remains the only migration history. DGX Spark
is not required for S92 persistence work because deterministic mock vectors are
sufficient to verify storage and integrity. A live provider check will be
announced before execution if this boundary changes.

This slice adds no table, migration, route, or persistent record.

## Verification

```text
boundary audit: PASS private payloads=5 owner targets=4 dgx required=False
focused tests: 4 passed; target statement/branch coverage: 100%
aggregate regression: 6339 passed, 1 known warning
statement=76322/77203=98.85885263526029%
branch=17726/18376=96.46277753591642%
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI
```
