# Slice 0685: AG operator review case SLA/escalation protected routes

## Intent

Expose the S69 SLA policy, aging, and escalation candidate read models through
protected AG operator-review case routes.

## Scope

- Add `GET /admin/v1/operator-review/cases/sla-policy`.
- Add `GET /admin/v1/operator-review/cases/aging`.
- Add `GET /admin/v1/operator-review/cases/escalations`.
- Keep all three routes authenticated with the existing AG operator-review guard.
- Register the static routes before `{case_id}` routes so they cannot be treated
  as case ids.
- Reuse existing case-list filters and deterministic `now` evaluation for aging
  and escalation projections.

## Decision

The routes are read-only projection surfaces. They do not persist escalation
state, send notifications, or call external incident systems. PostgreSQL-backed
validation remains deferred to the later protected smoke slice.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
```

## Result

The targeted tests cover route ordering, authentication, filter propagation,
invalid-filter problem responses, deterministic reference time handling, policy
problem conversion, and escalation candidate payload shape.
