# Slice 1167: MO authenticated runtime observability API

## Goal

Expose the runtime observation service behind the established MO service-claim
boundary without changing service readiness or prematurely introducing
contract drift.

## Result

- Added `GET /api/v1/model-runtime-observability` through an isolated route
  registrar using the existing `nex-mo` audience and service scope checks.
- Added an optional boolean `force_refresh` query that bypasses only the TTL
  cache; it cannot supply a target, command, port, path, or credential.
- Returned diagnostic `HEALTHY`, `DEGRADED`, `UNAVAILABLE`, or `UNKNOWN`
  snapshots with HTTP 200 after successful authorization.
- Preserved a safe `UNKNOWN` response when collection or configuration fails.
- Kept the operation out of `/ready`; observability failure remains diagnostic.
- Deferred main-app registration and OpenAPI exposure to Slice 1169 so runtime,
  canonical schema, fixture indexes, and exact operation parity change
  atomically. This Slice proves the authenticated route behavior in isolation.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_runtime_observability_api.py
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observability_api.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_runtime_observability_api.py \
  --coverage-target services/nex-mo/nex_mo/runtime_observability_api.py \
  --smoke scripts/smoke/run_mo_runtime_observability_api.py
```

## Quality Evidence

- Focused API regression: `6 passed`; changed API and smoke scopes
  statement/branch `100%/100%`.
- Slice Gate: `711 passed`, `2` protected PostgreSQL skips.
- Repository coverage: statement `99.80%`, branch `99.25%`; changed API scope
  `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Isolated HTTP evidence returned `401` without a service claim and `200` with
  a valid claim, including all `3/3` model observations.
