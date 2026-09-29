# Slice 1102: MO current-state re-audit boundary

## Goal

Start S111 by freezing the NeX-MO current-state re-audit boundary before adding
another provider feature, persistent control-plane record, or runtime profile.

## Decision

- The audit covers `MO-FR-001` through `MO-FR-005`: provider aliases, model
  execution, readiness and runtime evidence, deterministic mock/protected live
  modes, and provider resource metrics.
- Repository code, contracts, deterministic regression, and protected live
  provider evidence are primary. NeX-PCX request profiles remain explicit
  compatibility-only paths.
- Refactoring precedes feature work where evidence proves secret or model-path
  exposure, stale mock naming, unsafe coupling, contract drift, or an oversized
  module that blocks isolated change.
- S111 requires protected live embedding, reranking, and generation evidence.
  PostgreSQL evidence is not required because the current MO runtime owns no
  durable records or schema.
- Slice 1102 adds no table or migration and does not mutate provider state.
- A durable provider control plane, production secret manager, multi-DGX
  routing, load testing, and disaster-recovery certification remain deferred.

## Slice Plan

1. Slice 1102: current-state boundary audit.
2. Slice 1103: MO capability traceability inventory.
3. Slice 1104: provider catalog and configuration drift audit.
4. Slice 1105: remote transport and runtime coupling audit.
5. Slice 1106: route privacy refactoring checkpoint.
6. Slice 1107: model precision and resource-safety audit.
7. Slice 1108: contract and API drift audit.
8. Slice 1109: resilience, telemetry, and readiness audit.
9. Slice 1110: protected live provider re-audit.
10. Slice 1111: S111 closure and S112 handoff.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_mo_current_state_reaudit_boundary.py --summary

./.venv/bin/pytest -q \
  tests/test_mo_current_state_reaudit_boundary.py \
  --cov=run_mo_current_state_reaudit_boundary \
  --cov-branch --cov-report=term-missing
```
