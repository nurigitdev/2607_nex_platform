# Slice 0683: AG operator review case aging/stale assignment projection

## Intent

Add the S69 case aging read model so operators can see overdue, warning, watch,
closed, and stale-assignment states before escalation routing is exposed.

## Scope

- Add `ag_operator_review_case_aging.v1`.
- Compute case age and inactivity seconds from safe timestamps.
- Derive SLA state from the Slice 0682 priority policy.
- Mark stale assignments for assigned cases whose inactivity exceeds the
  priority warning threshold.
- Keep output metadata-only and linked to existing case queue/detail/timeline
  surfaces.

## Decision

Case aging remains a read model over existing `ag_op_cases` data. It does not
create a table, send notifications, persist acknowledgement history, or sync an
external incident system.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
```

## Result

The targeted tests cover overdue, warning, watch, closed, stale assignment,
malformed timestamp, redaction, deterministic reference time, and service wrapper
paths.
