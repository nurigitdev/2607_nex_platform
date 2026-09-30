# Slice 1154: MO provider telemetry migration and repository

## Goal

Add the compact MO-owned telemetry table and a SQLAlchemy repository that
atomically accumulates provider outcomes across processes.

## Result

- Migration `1154_mo_provider_telemetry` creates the compact
  `mo_provider_telemetry` table with counter and aggregate invariants.
- A deterministic SHA-256 key keeps the physical primary key bounded while a
  unique constraint protects the four-field logical identity.
- One portable `ON CONFLICT DO UPDATE` statement increments all counters and
  updates only the applicable final-outcome or retry diagnostic fields.
- The repository supports SQLite regression and PostgreSQL runtime without
  dialect-specific behavioral branches.
- A newly constructed repository recovers the same aggregate, and protected
  cleanup removes smoke evidence without exposing private provider values.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_repository.py \
  tests/test_mo_provider_telemetry_repository_smoke.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_repository.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_telemetry_repository.py \
  --test tests/test_mo_provider_telemetry_repository_smoke.py \
  --coverage-target services/nex-mo/nex_mo/provider_telemetry_persistence.py \
  --coverage-target services/nex-mo/nex_mo/provider_telemetry_repository.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_repository.py
```

## Quality Evidence

- Focused repository regression: `12 passed`.
- Slice Gate: `568 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.75%`, branch `99.04%`; changed persistence and
  repository scopes both `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- SQLite smoke recovered one request, two attempts, and one retry through a new
  repository instance, then removed the single evidence row.
