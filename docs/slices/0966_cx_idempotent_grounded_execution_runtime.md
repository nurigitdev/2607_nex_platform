# Slice 0966: CX Idempotent Grounded Execution Runtime

## Goal

Make the bounded synchronous generation facade owner-scoped, idempotent, and
durable before introducing the restart-safe read model.

## Implementation

- Added the short `cx_gen_admissions` table with owner-scoped uniqueness,
  SHA-256-only idempotency identity, semantic request hash, bounded lease, and
  terminal execution status.
- Added atomic SQLite/PostgreSQL-compatible admission reservation with exact
  replay, payload conflict rejection, in-progress rejection, and expired-lease
  reclaim.
- Derived generation IDs from tenant, owner, and the idempotency-key hash so
  retries keep a stable identity without storing the raw key.
- Added a coordinator that writes full output to owner-private storage, writes
  only safe metadata to `cx_generation_executions`, and then marks admission
  terminal.
- Added partial-commit repair: if the execution row exists but admission still
  says `IN_PROGRESS`, retry repairs the terminal state and replays without a
  second provider call.
- Wired the runtime into the generation POST route and enabled it only for the
  PostgreSQL service persistence mode. Existing memory-mode regression routes
  remain unchanged.
- Failed executions are also durable and replay as the original problem class
  without calling the provider again.
- Kept prompt, messages, output text, provider URL, and raw idempotency key out
  of the admission and execution tables.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_generation_runtime.py \
  tests/test_nex_cx_generation.py \
  tests/test_nex_cx_generation_repository.py \
  tests/test_nex_cx_generation_persistence.py \
  --cov=nex_cx.generation_runtime \
  --cov=nex_cx.generation \
  --cov=nex_cx.generation_repository \
  --cov=nex_cx.generation_persistence \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_grounded_generation_runtime_boundary_audit.py \
  --summary
```

- Focused runtime/repository/persistence suite: `135 passed`; the new
  `generation_runtime` module reached `98%` statement/branch coverage.
- Expanded generation, route, main-bootstrap, and drift regression:
  `192 passed`.
- Boundary audit: `pass`, eight gaps tracked, three still open, with Slice
  0967 selected next.
- Final quality gate: `7461 passed`, statement coverage `98.89%`, branch
  coverage `96.61%`.
- Contract gate: 87 schemas, 138 examples, 103 negative cases, and 7 OpenAPI
  documents passed.
- Quality gate exit status: `0`.

PostgreSQL and DGX remain intentionally deferred to the protected Slice 0969
evidence run.
