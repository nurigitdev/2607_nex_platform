# P8-S24 Delegation Lineage Persistence

## Scope

Add one immutable WC-owned lineage relation and matching repository boundary.
Existing P7 WorkItems remain readable and valid when no lineage row exists.

## Persistence

- migration head: `1004_wc_delegation_lineage`
- table: `wc_delegation_lineage`
- existing `wc_work_item`, `wc_claim`, and `wc_assignment` tables are unchanged
- root, parent WorkItem, and parent Claim references use foreign keys
- first-level and nested lineage shapes are enforced by a database constraint
- lineage has no update path; create replay must be semantically identical

## Runtime Boundary

- deterministic governance policy and policy semantic hash
- in-memory repository for deterministic regression
- SQLAlchemy repository for PostgreSQL runtime wiring
- missing lineage is a valid historical P7 state, not an error

## Verification

- focused repository and migration tests: `25 passed`
- new module statement coverage: `100.00%`
- new module branch coverage: `100.00%`
- P7/WC compatibility regression: `297 passed, 8 protected skips`
- P8-S23 contract regression: `9 passed`
- whitespace validation: pass

Actual PostgreSQL migration and restart evidence remains reserved for the
P8-S31 protected gate. The S24 SQL repository is regression-tested with a real
SQLAlchemy session and deterministic SQLite database; no concurrency claim is
made by this Slice.
