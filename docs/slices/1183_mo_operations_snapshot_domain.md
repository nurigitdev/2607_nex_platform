# Slice 1183: MO operations snapshot domain

## Goal

Define an immutable, privacy-safe operations snapshot and deterministic status
precedence before composing live service dependencies.

## Result

- Added validated source assessments for catalog, readiness, telemetry, and
  runtime facts.
- Added per-capability operational views for embedding, reranking, and
  generation with public identity, aggregate counters, and safe failure codes.
- Fixed precedence to `UNAVAILABLE > DEGRADED > UNKNOWN > READY` and made any
  missing required source or capability produce `UNKNOWN` rather than `READY`.
- Kept protected acceptance status separate from current operational status so
  an old acceptance result cannot mask current degradation.
- Built wire projections by allowlist; provider endpoints, keys, paths, payloads,
  prompts, and database details have no domain fields.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_operations_snapshot.py
./.venv/bin/python scripts/smoke/run_mo_operations_snapshot_domain.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo
```

## Executed evidence

- Domain evidence passed with four sources, three ready capabilities, and no
  private projection fields.
- NeX-MO Slice Gate passed `860` tests with `3` protected PostgreSQL skips.
- Statement coverage was `99.85%`, branch coverage was `99.46%`, and the new
  operations snapshot module reached `100%` statement and branch coverage.
