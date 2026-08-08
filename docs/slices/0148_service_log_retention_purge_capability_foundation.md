# Slice 0148: Service Log Retention Purge Capability Foundation

## Scope

Slice 0148 adds a guarded retention purge capability to the shared
`ServiceLogStore` abstraction.

Implemented:

- `ServiceLogStore.purge_retention_candidates(...)`
- InMemory retention scan, dry-run, blocked execute, and guarded delete paths
- SQLAlchemy retention scan, dry-run, blocked execute, and guarded delete paths
- execute success contract example
- SQLite regression coverage for persistent behavior

## Guardrails

The purge method is safe by default:

- `dry_run=True` scans candidates but deletes nothing.
- `dry_run=False` with `delete_enabled=False` returns a `BLOCKED` execution.
- `dry_run=False` with `delete_enabled=True` deletes at most
  `max_delete_count` oldest candidates for the selected service and cutoff.

Every path returns `service_log_retention_execution.v1` evidence.

## Boundary

This Slice does not expose HTTP control endpoints, dispatch retention from AG,
or run scheduled retention workers. Those remain service/API integration work.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_service_logs.py tests/test_contract_validation.py
```

Quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
