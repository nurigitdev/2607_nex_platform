# Slice 0721: AG dispatch live-provider boundary audit and refactoring checkpoint

## Intent

Start S73 by defining the boundary for future live dispatch providers without
making any external network calls in this slice.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py`.
- The audit verifies the closed S72 baseline, existing AG dispatch outbox table,
  bounded worker/result contracts, redaction guards, operations dashboard
  visibility, protected PostgreSQL smoke baseline, documentation, and quality
  gate wiring.
- Added regression coverage in
  `tests/test_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py`.

## Boundary

Slice 0721 does not enable live notification delivery, live external incident
sync, or any outbound HTTP call. Provider work remains readiness-only. Future
slices must add provider profile hardening, mock HTTP transports, HTTP client
timeouts/retries/idempotency, privacy regression, and protected PostgreSQL smoke
before a real live endpoint can be activated.

## Next Slices

- Slice 0722: provider profile/config registry hardening.
- Slice 0723: notification provider contract and mock HTTP adapter.
- Slice 0724: external incident provider contract and mock HTTP adapter.
- Slice 0725: redaction-aware HTTP client foundation.
- Slice 0726: execution worker provider routing integration.
- Slice 0727: provider result diagnostics dashboard.
- Slice 0728: live-provider privacy regression pack.
- Slice 0729: dispatch provider PostgreSQL smoke.
- Slice 0730: S73 dispatch provider readiness closure.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py -q --cov=run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit --cov-branch --cov-report=term-missing
```

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_live_provider_boundary_audit.py --summary
```
