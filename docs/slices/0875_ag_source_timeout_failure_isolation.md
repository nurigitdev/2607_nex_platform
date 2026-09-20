# Slice 0875: AG source timeout and failure isolation

## Goal

Bound AG audit-integrity source reads so one slow or unavailable source cannot
block the complete operations projection or expose internal errors.

## Implementation

- Added a bounded source-isolation executor driven by the S88 policy.
- Default source timeout is 2,000 ms, slow threshold is 1,000 ms, and worker
  count is capped at two and never exceeds admission capacity.
- Operational-event and evidence-export reads run independently.
- A timed-out source reports `TIMEOUT`; an exception reports `UNAVAILABLE`.
  Either condition degrades the projection while preserving any healthy source.
- Metrics retain only completed, failed, timeout, slow, and elapsed counters.
  Raw exceptions, SQL, credentials, payloads, and source records are excluded.
- Future cancellation is attempted after timeout. Python cannot forcibly stop a
  running thread; PostgreSQL statement timeout remains the final query ceiling.
- No table or migration was introduced.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_ag_resilience_performance.py \
  tests/test_nex_ag_audit_evidence_operations.py \
  --cov=nex_ag.resilience_performance \
  --cov=nex_ag.audit_evidence_operations \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
focused source-isolation/API tests: 78 passed
resilience policy, audit operations, and audit API statement/branch: 100%
contract validation: schemas=79 examples=129 negative_examples=92 openapi=7
aggregate regression: 5970 passed, 1 known warning
statement=73159/74040=98.810102647218%
branch=17156/17806=96.349545097158%
```
