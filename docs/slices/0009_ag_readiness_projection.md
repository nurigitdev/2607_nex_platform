# Slice 0009 AG Readiness Projection

Status: Implemented.

Backlog candidate: `S1-009` AG service readiness projection.

Requirement coverage: `AG-FR-001`.

## Scope

Slice 0009 adds the first read-only AG service projection:

- `services/nex-ag/nex_ag/readiness.py`.
- `GET /admin/v1/readiness/services`.
- API-based status collection from `/health`, `/ready`, and `/version`.
- Summary counts for `READY`, `NOT_READY`, `DEGRADED`, and `UNAVAILABLE`.
- `contracts/schemas/service/nex_ag/readiness_projection.v1.schema.json`.
- Positive and negative AG readiness projection fixtures.

AG does not read service databases. It consumes service-owned APIs and keeps the
projection safe for operator display.

## Evidence

Quality gate target:

```text
pytest with statement coverage and branch coverage
coverage threshold check
contract validation with AG readiness fixtures
```

## Follow-Up

Slice 0010 should produce the first traceable smoke evidence that links AE, CX,
MO, and AG through one trace ID.
