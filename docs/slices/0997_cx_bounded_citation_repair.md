# Slice 0997: CX Bounded Citation Repair

## Goal

Allow one automatic citation-only repair attempt during asynchronous grounded
generation without changing the admitted retrieval package.

## Implementation

- Repairs only missing citations and citations outside the admitted evidence
  selection; malformed or incomplete provider outputs retain normal recovery.
- Reuses the original grounded messages and exact retrieval package identity,
  appending a deterministic instruction limited to admitted citation labels.
- Allows exactly one repair provider request. A second validation failure is
  returned to the existing job retry and failure policy without another call.
- Never includes the invalid first output in the repair prompt, public job,
  logs, or durable metadata.
- Records safe repair attempt metadata in the worker result and uses the repair
  prompt hash for the completed generation execution record.
- Adds no route, table, migration, or direct CX-to-provider dependency; calls
  continue through the injected NeX-MO generation client.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_citation_repair.py \
  --test tests/test_nex_cx_async_generation_worker.py \
  --test tests/test_cx_mvp_integration_ae_handoff_boundary_audit.py \
  --coverage-target services/nex-cx/nex_cx/citation_repair.py \
  --coverage-target services/nex-cx/nex_cx/async_generation_worker.py
```

## Observed Evidence

- Slice Gate: `2,205 passed`.
- CX statement coverage: `99.01%`.
- CX branch coverage: `98.10%`.
- Citation repair and async worker statement/branch coverage:
  `100%`/`100%` each.
- Contract validation: `91` schemas, `142` positive examples, `107` negative
  examples, and `7` OpenAPI documents.
- Boundary audit: resolved gaps `5/8`, next Slice `0998`.
