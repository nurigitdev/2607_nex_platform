# Slice 0100: AG Cross-Service Observability Smoke

## Scope

Slice 0100 adds a guarded smoke pack proving that AG can observe service-owned
runtime records through the DB-backed operations source registry added in
Slice 0099.

Implemented:

- `scripts/smoke/run_ag_cross_service_observability_smoke.py`
- quality gate skip-summary hook
- `NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE`
- `NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE_PROFILE`
- SQLite regression coverage for the smoke execution path

## Smoke Flow

The guarded smoke is test-profile-only.

When enabled, it:

1. resolves the CX test database URL
2. applies CX migrations
3. builds CX with PostgreSQL persistence
4. uploads a smoke document and runs CX processing
5. builds AG with `NEX_AG_OPERATIONS_SOURCE_MODE=postgres`
6. calls `GET /admin/v1/operations` for the CX trace
7. verifies the CX processing job and lifecycle events are visible
8. deletes the smoke job/event rows

## Safety

The default quality gate keeps this smoke skipped:

```text
NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE=0
```

Live execution must use:

```text
NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE=1
NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE_PROFILE=test
```

The smoke refuses non-test profiles because it writes temporary CX processing
records before validating AG read-side observability.

## Evidence

Regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py
```

Full gate:

```bash
scripts/quality/run_quality_gate.sh
```

Default smoke summary:

```text
ag_cross_service_observability_smoke=skipped reason=NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE
```

Optional local PostgreSQL smoke:

```bash
NEX_AG_CROSS_SERVICE_OBSERVABILITY_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL=<cx-test-database-url> \
./.venv/bin/python scripts/smoke/run_ag_cross_service_observability_smoke.py --summary
```

Observed result:

```text
ag_cross_service_observability_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL events=2
```
