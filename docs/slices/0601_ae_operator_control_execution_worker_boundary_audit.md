# Slice 0601: AE operator-control execution worker boundary audit

## Scope

Start S61 by freezing the AE-owned operator-control execution worker boundary
after the S60 execution track closure.

## Decision

- AE remains the artifact, operator-control execution, worker execution, and
  persistence system of record.
- AG remains an operator-facing dispatcher/projection surface and must continue
  to call AE APIs instead of writing AE tables or controlling AE processes.
- The worker must consume S60 execution request/state/transition contracts and
  start only from an `ADMITTED` execution state.
- The first worker mode is a bounded fake dry-run supervisor dispatch worker
  that reuses the existing AE supervisor command/result contracts and fake
  supervisor adapter.
- Worker progress must be recorded as explicit AE-owned execution state and
  transition persistence.
- Real subprocess start/stop, production continuous start, JobQueue enqueue for
  operator control, and physical deletion remain disabled.

## Implementation

- Added
  `scripts/smoke/run_ae_operator_control_execution_worker_boundary_audit.py`.
- Added regression coverage for pass/fail evidence, required path checks,
  source-token checks, protected env redaction, helper behavior, and CLI output.
- Registered the audit in the default quality gate.
- Indexed Slice 0601 and added AE/AG README notes.

## Guardrails

- Slice 0601 does not add a worker route or invoke a supervisor adapter.
- Slice 0601 does not start/stop subprocesses, enqueue JobQueue work, run a
  worker, write PostgreSQL rows, or delete artifacts.
- Protected PostgreSQL smoke remains a later opt-in step and must use the real
  test DB when enabled.
- Evidence redacts database URLs, service tokens, provider keys, idempotency
  keys, local storage paths, and raw private payload markers.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_operator_control_execution_worker_boundary_audit.py tests/test_ae_operator_control_execution_worker_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ae_operator_control_execution_worker_boundary_audit.py -q --cov=run_ae_operator_control_execution_worker_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ae_operator_control_execution_worker_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

Observed audit summary:

```text
ae_operator_control_execution_worker_boundary_audit=pass paths=14/14 tokens=33/33 token_groups=9/9 boundary=ae_owned_bounded_fake_dry_run_worker_test_profile_only mode=blocked_until_worker_contract first_mode=fake_dry_run_supervisor_persistent_dispatch_worker next=Slice_0602
```

Observed targeted coverage:

```text
scripts/smoke/run_ae_operator_control_execution_worker_boundary_audit.py 100%
```

Observed quality gate coverage:

```text
statement_coverage=98.56% threshold=95.00%
branch_coverage=95.66% threshold=85.00%
```

## Next

- Slice 0602 should add the AE-owned execution worker plan/command contract
  that turns an admitted fake-dispatch execution state into a bounded worker
  command without opening real subprocess control or physical deletion.
