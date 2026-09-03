# Slice 0548: AG scheduler daemon lifecycle projection

## Scope

Project AE-owned artifact retention scheduler daemon lifecycle signals into AG
operations without giving AG runtime authority over the daemon process.

## Implementation

- `build_artifact_retention_daemon_lifecycle_projection` converts AE runtime
  observation metadata into a compact AG lifecycle projection.
- AG now preserves AE runtime `runtime_state`, `bounded_loop_result`,
  `shutdown_transition`, and `retry_circuit_guard` fields through its runtime
  normalization layer.
- Runtime-state lifecycle status takes precedence over heartbeat inference.
  Heartbeat status is still used as a fallback for older AE responses.
- The top-level daemon operations projection now includes
  `lifecycle_projection` and lifecycle summary fields for dashboard use.
- Lifecycle attention highlights failed runtime state, circuit-open retry
  guards, graceful shutdown in progress, retry backoff, and observation gaps.

## Guardrails

- The projection is metadata-only.
- AE remains the system of record for daemon runtime state, process control,
  JobQueue admission, worker execution, history writes, and physical purge.
- AG still cannot write AE persistence, enqueue AE jobs directly, or control the
  daemon process.
- Projectors use explicit allowlists and keep storage paths, database URLs, raw
  artifact payloads, and execution payloads out of AG responses.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
