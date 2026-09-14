# Slice 0762: AG dispatch daemon control audit events

## Objective

Add safe operational audit events for protected AG operator review escalation
dispatch daemon controls before adding control-history read models.

## Scope

- Added the
  `ag_operator_review_escalation_dispatch_daemon_control_audit_event.v1`
  detail shape.
- Added event types for dispatch daemon control success, rejection, and failure:
  - `ag.operator_review_escalation_dispatch_daemon.control.succeeded`
  - `ag.operator_review_escalation_dispatch_daemon.control.rejected`
  - `ag.operator_review_escalation_dispatch_daemon.control.failed`
- Wired `GET/POST /admin/v1/operator-review/dispatch-daemon/tick-plan` and
  `POST /admin/v1/operator-review/dispatch-daemon/tick-once` to emit safe audit
  events through `OperationalEventEmitter`.
- Kept problem responses unchanged while still recording rejected and failed
  control attempts in `service_operational_events`.
- Kept event details free of raw request payloads, raw provider payloads,
  credentials, database URLs, and external endpoint secrets.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon" --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `12 passed`; covered success, rejected, failed, and no-emitter audit
branches for the dispatch daemon control routes.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5107 passed`; total statement coverage `98.67%`, branch coverage
`96.02%`.
