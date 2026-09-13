# Slice 0696: AG operator review escalation operations dashboard

## Intent

Surface persisted S70 escalation action state in the AG operations dashboard and
issue-candidate projection.

## Scope

- Add `operator_review_escalations` to
  `ag_operations_dashboard_snapshot_projection.v1`.
- Wire the optional escalation store through AG operations dashboard and
  issue-candidate routes.
- Add dashboard summary, recent rows, action-required rows, source status, and
  safe route links for persisted escalation state.
- Add `operator_review_escalation_action_required.v1` to the issue-candidate
  rule family.
- Keep acknowledged/snoozed escalations visible in the dashboard without
  treating them as immediate action candidates.

## Decision

Persisted escalation action state is intentionally separated from the S69
candidate projection. The dashboard now shows both concepts: generated
candidate escalations remain under `operator_review_cases.escalations`, while
operator action state lives under `operator_review_escalations`.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

AG operators can see persisted escalation state and actionable escalation
signals from the same operations dashboard surface without exposing raw
comments, notification payloads, external incident payloads, database URLs,
tokens, or idempotency keys.
