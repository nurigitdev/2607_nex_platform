# Slice 0050 Generation Recovery Mock Flow

Status: Implemented.

Backlog candidate: `S5-010` Generation recovery mock flow regression.

Requirement coverage: `AEAPI-FR-005`, `CX-FR-008`, `AG-FR-003`,
`AG-FR-005`, `TRACE-GEN-001`, `PLAT-FR-007`.

## Scope

Slice 0050 adds an executable in-process recovery smoke:

- CX receives a generation request and stores a retryable `FAILED` execution
  record when the mock MO client raises `mo.provider_timeout`.
- CX exposes the failed progress timeline with `generation.failed`.
- AE creates an `ae_generation_recovery_request.v1` retry request for the
  failed CX record.
- AG assembles a recovery-aware generation audit projection with the AE recovery
  request summary.
- The global quality gate now runs this recovery smoke after the existing
  grounded success smoke.

The smoke is deterministic and uses FastAPI `TestClient` instances only. It does
not require live DGX, live MO, object storage, or PostgreSQL writes.

## Files

- `scripts/smoke/run_generation_recovery_mock_flow.py`
- `scripts/quality/run_quality_gate.sh`
- `tests/test_generation_recovery_mock_flow.py`

## Evidence

Slice evidence should include:

```bash
./.venv/bin/pytest tests/test_generation_recovery_mock_flow.py
scripts/quality/run_quality_gate.sh
```

The smoke prints:

```text
generation_recovery_mock_flow=pass trace_id=... cx=... recovery=... action=retry ag_action=retry
```

Regression tests cover failure/recovery/audit lineage, redaction guard, CLI
summary output, JSON evidence output, and assertion mismatch reporting.
