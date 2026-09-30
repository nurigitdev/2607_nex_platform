# Slice 1157: MO provider telemetry restart and concurrency hardening

## Goal

Prove restart recovery and prevent lost counters or regressed last-observation
diagnostics when multiple MO processes update one aggregate.

## Result

- Mutation timestamps are normalized to UTC `Z` before persistence so ordering
  comparisons are deterministic across runtime time zones.
- Counter increments remain unconditional and atomic; no successful request or
  retry is discarded when updates overlap.
- Final outcome and retry diagnostics advance only when their observed time is
  at least as recent as the durable value.
- `updated_at` is monotonic even when an older event commits after a newer one.
- An eight-worker SQLite regression and smoke prove 40 concurrent mutations,
  restart recovery through a new repository, latest-observation selection, and
  evidence cleanup. PostgreSQL concurrency is proved separately in Slice 1160.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_provider_telemetry_repository.py \
  tests/test_mo_provider_telemetry_restart_concurrency.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_telemetry_restart_concurrency.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_telemetry_restart_concurrency.py \
  --coverage-target services/nex-mo/nex_mo/provider_telemetry_persistence.py \
  --coverage-target services/nex-mo/nex_mo/provider_telemetry_repository.py \
  --smoke scripts/smoke/run_mo_provider_telemetry_restart_concurrency.py
```

## Quality Evidence

- Focused persistence, repository, and concurrency regression: `39 passed`.
- Slice Gate: `590 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.76%`, branch `99.07%`; changed persistence and
  repository scopes both `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Eight-worker smoke applied and recovered all `40/40` requests and attempts,
  selected the latest observed timestamp, and removed its evidence row.
