# Slice 1112: MO provider runtime hardening boundary

## Goal

Freeze the behavior-preserving S112 decomposition order and make the MO
persistence boundary explicit before changing provider runtime modules.

## Result

- Five extraction boundaries are ordered: public projection, catalog/config,
  response normalization, HTTP transport, and runtime telemetry.
- Public provider routes, response shapes, deterministic mock behavior, and
  requester injection remain compatibility guardrails.
- Provider catalog, active aliases, activation history, and bounded usage
  aggregates are PostgreSQL persistence candidates.
- High-frequency GPU/runtime samples remain external-metrics candidates.
- Endpoints, API keys, model paths, process commands, and request/response
  payloads must never enter durable persistence or public evidence.
- This boundary Slice creates no table or migration.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_runtime_hardening_boundary.py \
  --cov=nex_mo.runtime_hardening_boundary \
  --cov=run_mo_runtime_hardening_boundary \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_runtime_hardening_boundary.py --summary
```
