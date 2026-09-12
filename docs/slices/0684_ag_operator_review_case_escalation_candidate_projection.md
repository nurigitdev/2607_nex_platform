# Slice 0684: AG operator review case escalation candidate projection

## Intent

Add the S69 escalation candidate read model so AG can identify cases that need
operator attention before protected routes, dashboard wiring, or outbound
escalation execution are exposed.

## Scope

- Add `ag_operator_review_case_escalations.v1`.
- Reuse the Slice 0683 aging projection as the single SLA evaluation source.
- Select candidates for overdue, warning, watch, or stale-assignment cases.
- Attach deterministic escalation reasons, runbook ids, recommended operator
  actions, and safe links.
- Keep the projection metadata-only and free of raw case/action/resolution
  material.

## Decision

Escalation remains read-model-first. Slice 0684 does not create a new table,
send notifications, open external incidents, or persist escalation attempts.
The candidate projection is deliberately deterministic so future protected
routes, dashboard cards, privacy checks, and PostgreSQL smoke tests can assert
the same ordering and summary counts.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
```

## Result

The targeted tests cover candidate selection, deterministic sorting, summary
counts, runbook mapping, stale assignment, fallback actions, unsafe reason
filtering, redaction, service wrapper behavior, and empty projections.
