# Slice 0965: CX SQL Generation Runtime Repository

## Goal

Replace the process-only generation execution persistence boundary with an
owner-scoped SQL repository foundation that can bind public metadata to the
durable private output reference.

## Implementation

- Reused the existing `cx_generation_executions` table and added five short,
  nullable private-output reference columns rather than creating another table.
- Added an all-null or all-valid database constraint for schema version,
  backend, opaque `cx-private://` URI, SHA-256, and positive byte size.
- Added a partial unique index preventing two executions from sharing one
  private output URI.
- Added a SQLite/PostgreSQL-compatible SQLAlchemy repository with owner-scoped
  reads, immutable insert semantics, idempotent exact replay, rollback, and
  repository-unavailable mapping.
- Required completed rows to carry a hash-matching private output reference and
  prohibited failed rows from carrying one.
- Kept provider output, prompt, provider URL, and output preview outside SQL
  persistence.
- Deferred production route composition and request idempotency admission to
  Slice 0966.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_generation_repository.py \
  tests/test_nex_cx_generation_persistence.py \
  tests/test_nex_cx_generation_private_output.py \
  tests/test_cx_grounded_generation_runtime_boundary_audit.py \
  --cov=nex_cx.generation_repository \
  --cov=nex_cx.generation_persistence \
  --cov=nex_cx.generation_private_output \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_grounded_generation_runtime_boundary_audit.py \
  --summary
```

- Focused repository/persistence/private-output suite: `63 passed`; statement
  and branch coverage were both `100%` for all three modules.
- Expanded CX generation and database-drift regression: `191 passed`.
- The first full quality run detected two stale migration-count assertions
  (`19` instead of `20`); both were corrected and rerun successfully.
- Final quality gate: `7438 passed`, statement coverage `98.90%`, branch
  coverage `96.61%`.
- Contract gate: 87 schemas, 138 examples, 103 negative cases, and 7 OpenAPI
  documents passed.
- Boundary audit: `pass`, with the four remaining runtime-composition gaps
  intentionally assigned to Slice 0966 and later slices.

PostgreSQL and DGX remain intentionally deferred to the protected Slice 0969
evidence run.
