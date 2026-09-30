# Slice 1139: MO deterministic contract HTTP smoke

## Goal

Exercise the hardened MO API contract through real HTTP request handling while
proving that deterministic regression never reaches PostgreSQL or a remote
provider.

## Result

- Builds an isolated MO app with in-memory job/log persistence and forced mock
  provider mode.
- Verifies missing-auth rejection on all 15 protected operations.
- Executes all seven provider operations successfully and validates each public
  response against its canonical JSON Schema.
- Exercises documented `400`, `404`, and `422` problem responses across
  provider, job-control, and log-retention routes.
- Blocks external HTTP and records only counts and status metadata, never
  request or response payload content.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_contract_http_smoke.py
./.venv/bin/python scripts/smoke/run_mo_contract_http_smoke.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_contract_http_smoke.py
```

## Quality Evidence

- Focused regression: `66 passed`.
- Slice Gate: `445 passed`.
- Statement coverage: `99.67%` (threshold `95%`).
- Branch coverage: `98.73%` (threshold `94%`).
- Contract validation: `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- HTTP evidence: `15/15` protected operations rejected missing auth, `7/7`
  provider response contracts validated, `6/6` documented error statuses
  observed, and `0` external requests attempted.
