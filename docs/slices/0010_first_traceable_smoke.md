# Slice 0010 First Traceable Smoke

Status: Implemented.

Backlog candidate: `S1-010` First traceable smoke.

Requirement coverage: `TRACE-PLAT-001`, `TRACE-MO-001`.

## Scope

Slice 0010 adds the first executable trace smoke:

- `scripts/smoke/run_traceable_mock_flow.py`.
- Quality gate integration for the smoke command.
- AG readiness projection trace evidence.
- Regression tests for trace continuity across AE, CX, MO, and AG.

The smoke runs in-process with FastAPI `TestClient` instances. It does not
require local service servers, PostgreSQL, or live model providers.

## Evidence

Quality gate now ends with:

```text
traceable_mock_flow=pass trace_id=4bf92f3577b34da6a3ce929d0e0e4736 ...
```

The evidence object includes:

- AE chat interaction trace ID.
- CX generation execution trace ID.
- MO runtime metadata trace ID.
- AG readiness projection trace ID.

## Follow-Up

The next sprint can turn this in-process smoke into a local multi-service smoke
against running HTTP servers and then into protected live provider evidence.
