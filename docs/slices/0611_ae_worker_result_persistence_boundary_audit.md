# Slice 0611: AE worker result persistence boundary audit

## Scope

Start S62 by freezing the AE-owned operator-control execution worker result
persistence boundary before any worker result table or repository is added.

## Decision

- AE remains the system of record for worker result persistence.
- AG may later read/project worker result rows, but must not write AE result
  tables, enqueue AE jobs, or control AE processes directly.
- Slice 0611 does not create a database table. The first schema slice should be
  Slice 0612.
- The candidate result table name is `ae_op_exec_worker_results`, which keeps
  the PostgreSQL relation name short.
- A future event table name may be `ae_op_exec_worker_events`, but event
  persistence remains deferred until result rows are stable.
- Worker result writes must be explicit through `persist_worker_result=true`.
  Default route behavior remains non-persistent.
- The stored shape should be `safe summary + hashes`: ids, state/request
  linkage, scheduler/action/mode/status fields, observed time, bounded
  supervisor counts/statuses/actions/ids, guardrails, redacted metadata, and
  hashes for source command and transition plan.
- Persistence must not store the full worker command payload, full
  transition-plan payload, or full supervisor result payload.

## Guardrails

- Do not store database URLs, service tokens, provider keys, local storage
  paths, artifact payloads, execution payloads, daemon runtime payloads, or
  supervised process snapshots.
- Do not replace S60/S61 execution state and transition evidence. Worker result
  rows should reference existing execution state identity.
- Do not enable worker-result blob storage.
- Do not enable AG direct database writes, AG JobQueue enqueue, real subprocess
  control, or physical deletion automation.
- Protected PostgreSQL smoke remains opt-in and must use the real test DB when
  enabled.

## Implementation

- Added
  `scripts/smoke/run_ae_operator_control_execution_worker_result_persistence_boundary_audit.py`.
- Added regression coverage for pass/fail evidence, table-name length checks,
  source-token checks, protected env redaction, helper behavior, and CLI output.
- Registered the audit in the default quality gate.
- Indexed Slice 0611 and added AE/AG README notes.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_operator_control_execution_worker_result_persistence_boundary_audit.py tests/test_ae_operator_control_execution_worker_result_persistence_boundary_audit.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_ae_operator_control_execution_worker_result_persistence_boundary_audit.py -q --cov=run_ae_operator_control_execution_worker_result_persistence_boundary_audit --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_ae_operator_control_execution_worker_result_persistence_boundary_audit.py --summary
./scripts/quality/run_quality_gate.sh
```

Observed audit summary:

```text
ae_operator_control_execution_worker_result_persistence_boundary_audit=pass paths=15/15 tokens=42/42 token_groups=11/11 tables=2/2 boundary=ae_owned_safe_summary_worker_result_persistence result_table=ae_op_exec_worker_results next=Slice_0612
```

Observed targeted coverage:

```text
tests/test_ae_operator_control_execution_worker_result_persistence_boundary_audit.py: 6 passed
run_ae_operator_control_execution_worker_result_persistence_boundary_audit.py statement_coverage=100% branch_coverage=100%
```

Observed quality gate coverage:

```text
4302 passed
statement_coverage=98.57% threshold=95.00%
branch_coverage=95.71% threshold=85.00%
```

## Next

- Slice 0612 should add the AE worker result schema/migration foundation using
  `ae_op_exec_worker_results` and the safe summary projection fixed here.
