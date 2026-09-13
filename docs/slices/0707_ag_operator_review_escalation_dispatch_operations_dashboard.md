# Slice 0707: AG operator review escalation dispatch operations dashboard

## Intent

Surface the S71 escalation dispatch outbox in the AG operations dashboard and
issue-candidate feed without introducing live provider delivery.

## Scope

- Add `operator_review_escalation_dispatches` to
  `ag_operations_dashboard_snapshot_projection.v1`.
- Wire an optional dispatch store through AG operations dashboard and
  issue-candidate projection builders.
- Add dispatch summary, recent rows, attention rows, source status, route links,
  and safe redaction metadata.
- Add `operator_review_escalation_dispatch_attention_required.v1` for failed,
  pending, in-flight, and retry-wait dispatch rows.
- Keep `SUCCEEDED` and `CANCELLED` rows visible in recent history while
  excluding them from attention candidates.

## Decision

Dispatch operations visibility remains read-model only. S71 dashboard state uses
the safe `ag_op_esc_dispatches` outbox records introduced in Slice 0702 and does
not execute notification, email, webhook, or incident providers. The dashboard
and issue-candidate feed continue to expose only safe refs, hashes, previews,
status counters, and route templates.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operations.py tests/test_nex_ag_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

AG operators can now see escalation dispatch outbox health from the same
operations dashboard that already shows S70 escalation state, and failed or
pending dispatch rows generate safe issue candidates for triage.
