# Slice 1119: MO runtime decomposition architecture guard

## Goal

Turn the S112 refactoring result into a repeatable architecture guard so later
features cannot silently recreate oversized modules or reverse dependencies.

## Result

- Eight MO runtime modules have explicit line budgets and dependency rules.
- The provider API composition module is reduced from 825 to below 550 lines.
- The remote execution module is reduced from 1,768 to below 1,200 lines.
- Catalog, projection, registry, normalization, and telemetry cannot import the
  HTTP client or SQLAlchemy; HTTP remains in transport/preflight boundaries.
- Remote execution cannot import the provider API composition module.
- Five compatibility export groups remain machine-checked.
- Hybrid persistence is decided but intentionally not implemented in S112.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_runtime_hardening_audit.py \
  --cov=nex_mo.runtime_hardening_audit \
  --cov=run_mo_runtime_hardening_audit \
  --cov-branch --cov-report=term-missing

./.venv/bin/python scripts/smoke/run_mo_runtime_hardening_audit.py --summary
```
