# Slice 0096: AG operations source registry

## Intent

Slice 0096 introduces a shared AG operations source registry for job and
operational event sources. The goal is to keep AG's existing endpoints stable
while preparing one source model for unified operations projection and
DB-backed read-only wiring.

## Runtime Behavior

`nex_ag.operations` now provides:

- `OperationsSource`
- `OperationsSourceRegistry`
- `RegistryOperationalEventStore`
- `build_operations_source_registry`

An `OperationsSource` is scoped to one known service and can carry:

- a `JobQueue` read port
- an `OperationalEventStore` read port
- a source kind label such as `memory` or future `postgres`

`register_job_operation_routes()` and `register_operational_event_routes()` now
accept an optional registry. Existing direct injection parameters still work, so
this slice does not change route response shapes.

## Registry Event Store

`RegistryOperationalEventStore` is a read-only adapter over per-service event
stores. It aggregates event reads, applies service filters before querying each
source, sorts events by creation time, and rejects append attempts.

## Testing Boundary

This slice remains memory-first. PostgreSQL source wiring is deferred to a later
slice, but tests prove that the registry can already feed both existing AG
operations routes.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_ag_operations.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
