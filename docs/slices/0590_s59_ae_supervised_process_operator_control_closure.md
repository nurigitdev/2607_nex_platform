# Slice 0590: S59 AE supervised process operator-control closure

## Scope

Close the S59 guarded operator-control track with a quality-gate checkpoint.

## Implementation

- Added
  `scripts/smoke/run_s59_ae_supervised_process_operator_control_closure.py`.
- The closure verifies the full Slice 0581-0590 document sequence.
- It checks the AE operator-control boundary audit, policy/request/admission
  contracts, command preview, AE service facade, AE protected PostgreSQL smoke,
  AG projection, AG automation dashboard integration, AG-to-AE protected
  PostgreSQL smoke, and this closure checkpoint.
- It verifies quality-gate hooks for the S59 boundary audit, AE protected smoke,
  AG-to-AE protected smoke, automation dashboard smoke, and closure script.
- It scans S59 docs and service README notes for database URLs, local storage
  paths, provider keys, shared passwords, idempotency keys, and raw private
  payload markers.

## Guardrails

- AE remains the daemon process owner and persistence system of record.
- AG remains an operator-facing dispatcher/projection that must call AE APIs.
- Operator-control responses remain preview-only until a later protected
  execution Slice invokes a supervisor adapter.
- Operator-control evidence remains metadata-only; raw command bodies,
  idempotency keys, database URLs, provider keys, and local paths must not be
  emitted.
- Start/restart remains test-profile-only, explicitly opted in, approval
  guarded, and bounded.
- Restart continues to decompose to stop then start with distinct command
  preview evidence.
- `physical_delete_automation_enabled` remains false for this operator-control
  surface.
- Protected PostgreSQL smoke remains opt-in and requires real test databases.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_s59_ae_supervised_process_operator_control_closure.py tests/test_s59_ae_supervised_process_operator_control_closure.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_s59_ae_supervised_process_operator_control_closure.py -q --cov=run_s59_ae_supervised_process_operator_control_closure --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

Observed results:

- Targeted closure regression: `6 passed`, closure module coverage `97%`.
- Full quality gate: `3992 passed`, statement coverage `98.59%`, branch
  coverage `95.81%`.
- Protected PostgreSQL smoke runners remain opt-in by default; Slice 0589
  already verified the AG-to-AE operator-control path against the AE test DB.

Observed summary:

```text
s59_ae_supervised_process_operator_control_closure=pass slice_range=0581-0590 required_files=35 boundary=ae_owned ag_projection=read_only dashboard=operator_control smoke=test_db_protected
```

## Next

- Slice 0591 can start from this guarded preview baseline and move toward the
  next AE artifact lifecycle or operator execution track without giving AG
  direct process ownership.
