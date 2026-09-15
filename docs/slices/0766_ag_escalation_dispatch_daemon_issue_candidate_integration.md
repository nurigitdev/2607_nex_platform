# Slice 0766: AG dispatch daemon issue-candidate integration

## Objective

Promote failed or rejected AG dispatch daemon operator controls into the AG
operations issue-candidate projection.

## Scope

- Added the
  `operator_review_dispatch_daemon_control_attention_required.v1` issue rule.
- Reused the Slice 0765 `daemon_controls` dashboard section as the source of
  safe control-history signals.
- Emits one grouped candidate for recent `FAILED` or `REJECTED` control events.
- Candidate signal includes safe metadata only:
  - control event ids,
  - action/status rollups,
  - error and rejection codes,
  - route/control paths,
  - runbook ids and recommended operator actions.
- Kept source unavailability separate through the existing
  `operations_source_unavailable.v1` degraded-source candidate.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon or issue_candidate or rules" --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `40 passed, 151 deselected, 1 warning`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5113 passed, 1 warning in 302.96s`.

Coverage: statement `98.67%` (`65575/66457`), branch `96.04%`
(`15687/16334`).
