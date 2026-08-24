# Slice 0336: AG Generation Quality Disposition API Wiring

## Scope

Expose the AG operator disposition foundation through guarded admin routes and
record an operational audit event when a disposition is accepted.

## Implemented

- Added AG admin routes:
  - `POST /admin/v1/generation-audit/generations/{cx_generation_id}/quality-dispositions`;
  - `GET /admin/v1/generation-audit/generations/{cx_generation_id}/quality-dispositions`;
  - `GET /admin/v1/generation-audit/generations/{cx_generation_id}/quality-dispositions/{disposition_id}`.
- Reused the service-token authorization boundary used by other AG admin
  surfaces.
- Added list projection summary fields:
  - `count`;
  - `by_status`;
  - `latest_updated_at`.
- Emitted `ag.generation_quality.disposition_recorded` as an operational event
  without storing raw notes or note previews in event details.
- Kept audit-event emission best-effort so an audit store outage does not block
  the operator disposition write.
- Wired the routes into `nex_ag.main`.
- Extended `nex-ag` OpenAPI with request, record, and list schemas.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_quality_disposition.py -q
35 passed, 1 warning in 0.49s
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=54 examples=86 negative_examples=63 openapi=7
```

No PostgreSQL smoke is attached to this slice because route persistence is still
in-memory. PostgreSQL-backed persistence follows in the next slice.
