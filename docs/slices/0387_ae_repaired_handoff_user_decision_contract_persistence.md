# Slice 0387: AE Repaired Handoff User Decision Contract Persistence

## Scope

Add the user decision contract and persistence foundation for repaired response
handoffs.

This slice does not add service routes or PostgreSQL smoke execution. It defines
the safe record shape and database table used by Slice 0388 and Slice 0389.

## Implemented

- Added `ae_repaired_response_decision.v1` JSON Schema.
- Added `services/nex-ae-api/nex_ae_api/repaired_response_decisions.py`.
- Added `database/nex-ae-api/migrations/0387_ae_repaired_response_decision_persistence.sql`.
- Supported user decisions:
  - `accept_repair`: selected generation is the repaired CX generation;
  - `keep_original`: selected generation is the parent/original CX generation.
- Stored only safe decision material:
  - owner and conversation scope;
  - handoff and generation ids;
  - selected/rejected generation ids;
  - reason codes;
  - comment hash and short preview;
  - actor ref and metadata redaction flags.
- Added in-memory and SQLAlchemy stores with handoff/interactions list helpers.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_responses.py -q --cov=nex_ae_api.repaired_response_decisions --cov-branch --cov-report=term-missing
63 passed, 1 warning in 1.31s
repaired_response_decisions.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2827 passed, 1 warning in 79.09s
statement_coverage=98.67% threshold=95.00%
branch_coverage=96.11% threshold=85.00%
contract_validation=pass schemas=62 examples=92 negative_examples=68 openapi=7
```

Recommended next slice:

```text
Slice 0388: AE repaired handoff user decision service API wiring
```
