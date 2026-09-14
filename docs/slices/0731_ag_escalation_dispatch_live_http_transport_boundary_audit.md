# Slice 0731: AG dispatch live HTTP transport boundary audit

## Intent

Start S74 by defining the boundary for live HTTP transport readiness after S73
provider readiness closure.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.py`.
- The audit verifies S73 closure, provider config/request/result contracts,
  injectable HTTP client foundation, worker provider router, provider diagnostics
  dashboard, privacy regression, protected PostgreSQL smoke, documentation, and
  quality-gate hooks.
- The audit records the product decision that no external notification or
  incident endpoint exists yet, so protected live-shape smoke must use a local
  loopback HTTP server before any real external endpoint is considered.
- Added regression coverage in
  `tests/test_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.py`.

## Boundary

Slice 0731 does not implement real HTTP transport and does not make outbound
network calls. Real external endpoint smoke remains deferred until the broader
system is implemented. The next S74 slices should implement injected real
transport, outbound envelope/header guardrails, local loopback notification and
incident smokes, worker opt-in integration, PostgreSQL loopback smoke, and S74
closure.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.py -q --cov=run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit --cov-branch --cov-report=term-missing
```

Result: `6 passed`, `100%` statement coverage, `100%` branch coverage for the
boundary audit module.

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_transport_boundary_audit.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_live_http_transport_boundary=pass boundary=ag_owned_operator_review_escalation_dispatch_live_http_transport network=disabled smoke=local_loopback_http_server real_endpoint_deferred=True next=Slice_0732`.
