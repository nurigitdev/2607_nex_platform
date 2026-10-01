# Slice 1196: MO MVP protected acceptance API

## Goal

Expose a server-selected, read-only MO MVP acceptance projection through an
admin/service-claim protected operations API.

## Implementation

- Added `GET /admin/v1/operations/mvp-acceptance`.
- Service principals and users with the `admin` role may read the projection;
  viewers receive 403 and missing or invalid credentials receive 401.
- Clients cannot submit evidence or thresholds. The server selects the policy,
  evidence provider, and clock.
- Provider collection failures are redacted and return a fail-closed blocked
  projection rather than exception details.
- The repository provider supplies only closure inventory evidence. Until the
  remaining protected evidence providers are composed, the default projection
  remains blocked by the other eight gates.
- Runtime/OpenAPI parity remains closed at 29 operations, 25 protected.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_mo_mvp_acceptance_api.py \
  tests/test_mo_mvp_acceptance_api.py
./.venv/bin/python \
  scripts/smoke/run_mo_mvp_acceptance_api.py --summary
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_mo_mvp_acceptance_oa_transition_boundary_audit.py \
  --test tests/test_nex_mo_mvp_acceptance.py \
  --test tests/test_nex_mo_mvp_evidence_inventory.py \
  --test tests/test_nex_mo_mvp_acceptance_evaluation.py \
  --test tests/test_nex_mo_mvp_acceptance_api.py
```

## Result

- Authentication behavior: `401/403/200`.
- Accepted deterministic projection: gates `9/9`.
- Default repository projection: fail-closed `BLOCKED`.
- Slice Gate: `993 passed, 5 skipped`; statement coverage `99.87%`, branch
  coverage `99.55%`; API and smoke scope coverage `100%/100%`.
- Checkpoint Gate: `9142 passed, 10 skipped`; statement coverage `98.80%`,
  branch coverage `97.02%`; contract validation `129/187/155/7` and all five
  S120 smoke commands passed in `581.241s`.
- Next Slice: `1197`.
