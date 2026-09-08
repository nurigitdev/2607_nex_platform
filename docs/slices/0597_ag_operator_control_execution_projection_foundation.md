# Slice 0597: AG operator-control execution projection foundation

## Scope

Project AE-owned artifact retention scheduler daemon operator-control execution
read models into AG without giving AG direct execution authority.

## Decision

- AE remains the system of record for operator-control execution state and
  transition persistence.
- AG reads AE collection/detail read models through the service client contract.
- AG projections are metadata-only and redact raw execution requests,
  idempotency keys, database URLs, provider keys, and local storage paths.
- Collection filters support scheduler, action, execution status, idempotency
  status, and limit.

## Implementation

- Added AG projection schema versions for operator-control execution
  collection/detail read models.
- Extended `AeArtifactOperationsClient`, in-memory fixtures, and the HTTP
  source client with execution collection/detail methods.
- Added collection/detail projection builders, summaries, source-status
  metadata, route hints, and read-only operator guidance.
- Added regression coverage for projection summaries, redaction, in-memory
  read models, HTTP request shape, missing detail, and source-failure behavior.

## Guardrails

- AG does not write AE tables, enqueue AE jobs, invoke supervisor adapters,
  start/stop subprocesses, or perform physical deletion.
- Projections exclude raw `operator_control_execution_request`, nested
  transition state payloads, and idempotency keys.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q
./scripts/quality/run_quality_gate.sh
```

## Next

- Slice 0598 should expose the execution projections through protected AG
  admin routes.
