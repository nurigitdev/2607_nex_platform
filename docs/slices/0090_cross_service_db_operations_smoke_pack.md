# Slice 0090: Cross-service DB operations smoke pack

## Intent

Slice 0090 adds one guarded PostgreSQL smoke pack for the common DB operations
foundation. It keeps the default regression suite fast, while making it easy to
verify all service-owned test databases before DB-intensive slices continue.

## Runtime Behavior

The new smoke runner is:

```bash
./.venv/bin/python scripts/smoke/run_postgres_operations_smoke_pack.py --summary
```

Default behavior is skipped. To execute the write-capable smoke pack:

```text
NEX_DB_OPERATIONS_SMOKE=1
NEX_DB_OPERATIONS_SMOKE_PROFILE=test
NEX_DB_OPERATIONS_SMOKE_SERVICES=nex-ae-api,nex-ag,nex-cx,nex-mo,nex-oa
```

The pack is intentionally limited to the `test` profile. For each selected
service it verifies:

- database readiness using the service test DB env
- DB-backed JobQueue smoke
- DB-backed OperationalEventStore smoke

The JobQueue and OperationalEventStore sub-smokes apply service migrations and
clean up their own smoke rows. Evidence contains only env names, DB identity
metadata, redacted database URLs, sub-smoke statuses, and check summaries.

## Testing Boundary

The ongoing split is:

- SQLite regression: fast behavior, branch coverage, and adapter edge cases.
- Single-service PostgreSQL smoke: focused runtime semantics for one store.
- Cross-service PostgreSQL smoke pack: readiness and write-path confidence
  across all service-owned test databases.

Default quality gate runs the pack in skipped summary mode. Live execution is a
local operator action because it writes to PostgreSQL test databases.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_smoke_helpers.py`
- Default skipped smoke:
  `./.venv/bin/python scripts/smoke/run_postgres_operations_smoke_pack.py --summary`
- Optional PostgreSQL smoke pack:
  `NEX_DB_OPERATIONS_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_postgres_operations_smoke_pack.py --summary`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
