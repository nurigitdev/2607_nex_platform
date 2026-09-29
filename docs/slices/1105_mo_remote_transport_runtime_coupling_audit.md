# Slice 1105: MO remote transport and runtime coupling audit

## Goal

Measure MO provider registry, remote transport, normalization, telemetry, and
composition coupling before changing the privacy-sensitive public projection.

## Result

- `providers.py` and `remote_provider.py` exceed their refactoring budgets at
  830 and 1,768 lines respectively.
- The modules have bidirectional dependency pressure: provider routes import
  remote execution dynamically while remote execution imports catalog and route
  resolution statically.
- Process-local telemetry is coupled to HTTP transport and normalization.
- Immutable route/config values, centralized failure taxonomy, and requester
  injection are good boundaries and must be preserved.
- The ordered plan avoids a broad rewrite: privacy-safe projection first in
  Slice 1106, then catalog/environment extraction, remote module decomposition,
  and an explicit telemetry adapter in S112.
- Public APIs, deterministic mock behavior, and live request shapes remain
  unchanged in this audit Slice.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_coupling_audit.py --summary

./.venv/bin/pytest -q \
  tests/test_mo_runtime_coupling_audit.py \
  --cov=nex_mo.runtime_coupling_audit \
  --cov=run_mo_runtime_coupling_audit \
  --cov-branch --cov-report=term-missing
```
