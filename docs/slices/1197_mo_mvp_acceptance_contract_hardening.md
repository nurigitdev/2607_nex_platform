# Slice 1197: MO MVP acceptance contract hardening

## Goal

Freeze the protected MO MVP acceptance projection with a strict canonical JSON
Schema, indexed positive and privacy-negative fixtures, and OpenAPI binding.

## Contract

- `mo_mvp_acceptance_report.v1` requires exactly nine gate results and permits
  only normalized reason codes, summary counts, advisory deferrals, trace ID,
  source status, and server-selected metadata.
- The accepted fixture and the actual evaluator projection validate against the
  same canonical schema.
- Negative fixtures prove that `raw_evidence` and `database_url` are rejected.
- OpenAPI declares only `GET /admin/v1/operations/mvp-acceptance`; its response,
  gate, and blocker objects reject additional properties.
- The MO runtime/OpenAPI parity inventory now contains 21 canonical components.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_mo_mvp_acceptance_contracts.py
./.venv/bin/python scripts/smoke/run_mo_mvp_acceptance_contracts.py --summary
./.venv/bin/python scripts/quality/validate_contracts.py
```

No table or migration is added. Next Slice: `1198`.

## Result

- Slice Gate: `997 passed, 5 skipped`; statement coverage `99.87%`, branch
  coverage `99.55%`.
- Contract smoke scope: statement and branch coverage `100%/100%`, checks
  `8/8`, fixtures `1/2`.
- Contract validation: schemas `130`, examples `188`, negative examples `157`,
  OpenAPI documents `7`.
