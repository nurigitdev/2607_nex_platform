# Slice 1015: AE Workspace SQLAlchemy Repository

## Goal

Provide restart-safe workspace and activity persistence without coupling route
logic to SQL statements.

## Implementation

- Added `SqlAlchemyWorkspaceRepository` with create, read, append-activity, and
  ordered activity-list operations.
- Workspace creation is idempotent by `workspace_id`; a collision owned by a
  different tenant/user fails closed.
- Initial activity insertion and workspace creation share one transaction.
  Later activity insertion increments the workspace summary exactly once.
- PostgreSQL JSONB and SQLite JSON-text paths share one adapter contract.
- Database failures are mapped to a retryable, API-safe repository error.

Production route wiring remains deferred to Slice 1016. This Slice uses SQLite
for fast repository regression and does not mutate `nex_ae_test`.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_workspace_persistence.py \
  --test tests/test_ae_workspace_repository_smoke.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_persistence.py \
  --coverage-target scripts/smoke/run_ae_workspace_repository_smoke.py \
  --smoke scripts/smoke/run_ae_workspace_repository_smoke.py
```

Observed evidence:

- Focused repository regression: `8 passed`.
- Slice Gate: `1940 passed` with one known warning.
- Repository statement/branch coverage: `97.82%`/`95.50%`.
- Workspace repository and smoke runner statement/branch coverage:
  `100%`/`100%`.
- Contract validation: 92 schemas, 145 positive examples, 109 negative
  examples, and 7 OpenAPI documents.
- Deterministic smoke: checks `8/8`, one workspace, two ordered activities.
