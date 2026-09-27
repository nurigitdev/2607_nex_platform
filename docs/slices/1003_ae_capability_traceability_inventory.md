# Slice 1003: AE API/Web capability traceability inventory

## Goal

Map every SRS AE API and Web functional requirement to current repository
evidence before deciding whether its behavior is complete or needs refactoring.

## Decision

- The inventory covers six `AEAPI-FR-*` and five `AEWEB-FR-*` requirements.
- API requirements require implementation, contract, migration, test, and route
  evidence. Web requirements require implementation, contract, test, and
  browser route/composition evidence.
- Traceability means the implementation can be located and tested; it does not
  mean persistence, privacy, contract drift, or UX acceptance has passed.
- Repository evidence is authoritative and the inventory adds no schema.
- Persistence acceptance is intentionally deferred to Slice 1004.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ae_capability_traceability_inventory.py --summary

./.venv/bin/pytest -q \
  tests/test_ae_capability_traceability_inventory.py \
  --cov=nex_ae_api.current_state_traceability \
  --cov=run_ae_capability_traceability_inventory \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
inventory: PASS, requirements=11, traceable=11, evidence=78, issues=0
focused tests: 5 passed
new module statement/branch coverage: 100%
Slice Gate: 1,864 passed, 1 known warning
statement coverage: 97.72%
branch coverage: 95.40%
contract validation: 92 schemas, 145 examples, 109 negative examples, 7 OpenAPI
```
