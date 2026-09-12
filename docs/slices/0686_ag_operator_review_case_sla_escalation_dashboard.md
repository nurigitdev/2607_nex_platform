# Slice 0686: AG operator review case SLA/escalation dashboard integration

## Intent

Surface S69 SLA and escalation risk in the AG operations dashboard so operators
can monitor case urgency without opening the dedicated case routes first.

## Scope

- Add `sla_policy`, `sla_aging`, and `escalations` blocks to the
  `operator_review_cases` dashboard section.
- Reuse the existing case-list projection as the single input for rollup,
  queue, assignment workload, aging, and escalation summaries.
- Use one reference time per dashboard build for aging and escalation
  consistency.
- Keep the dashboard output summary-oriented and free of raw case/action text.
- Extend the operations projection schema to allow the new dashboard blocks.

## Decision

The dashboard integration remains read-only. It does not persist escalation
state, send notifications, create external incidents, or introduce new tables.
The dedicated protected routes from Slice 0685 remain the detailed surfaces.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

## Result

The operations dashboard regression suite passed with contract validation and
covered SLA policy summary, aging summary, escalation candidate summary, empty
filtered results, paths, and redacted candidate linkage.
