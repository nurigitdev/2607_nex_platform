# Slice 0585: AE operator-control service API facade

## Scope

Expose the AE-owned operator-control policy, admission, and command-preview
contracts through protected service APIs without executing process control.

## Implementation

- Added `ae_artifact_retention_scheduler_daemon_operator_control_facade.v1`.
- Added protected policy discovery:
  `/api/v1/artifact-retention/scheduler-daemon-operator-control-policy`.
- Added protected preview evaluation:
  `/api/v1/artifact-retention/scheduler-daemon-operator-control-preview`.
- The preview route builds the policy, validates the operator request, evaluates
  admission, and returns the command-preview facade in one response.
- `operator_subject` remains strict; `requested_by` fallback is accepted for
  existing AG-style callers and strips non-subject fields before validation.
- The scheduler config route discovery now includes both operator-control API
  routes.
- Added regression coverage for policy GET auth, preview POST auth, status
  probe, start fallback, restart decomposition, invalid idempotency, invalid
  boolean payloads, explicit subject key drift, facade validation drift, and
  redaction posture.

## Guardrails

- Slice 0585 is preview-only and does not dispatch supervisor commands.
- Slice 0585 does not invoke the supervisor adapter.
- Slice 0585 does not start, stop, or restart a subprocess.
- Slice 0585 does not write to the database or enqueue the JobQueue.
- AG remains an operator-facing caller/observer; AE remains the process-control
  owner.
- No database URLs, local storage paths, raw artifact payloads, raw execution
  payloads, raw daemon runtime payloads, raw supervised process snapshots,
  provider keys, or service tokens are emitted.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py services/nex-ae-api/nex_ae_api/artifacts.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_facade.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_policy.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_admission.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_command_preview.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_facade.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_routes.py tests/test_nex_ae_artifacts.py -q
./scripts/quality/run_quality_gate.sh
```

Quality gate result: `3953 passed`, statement coverage `98.58%`, branch
coverage `95.76%`.

## Next

- Slice 0586 should add protected PostgreSQL smoke evidence around the
  operator-control facade while keeping the route preview-only.
