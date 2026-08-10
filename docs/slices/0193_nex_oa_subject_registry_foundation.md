# Slice 0193: NeX-OA Subject Registry Foundation

## Scope

Slice 0193 adds the minimum NeX-OA subject registry required before CX can
migrate durable source ownership from legacy `tenant_id + owner_user_id` fields
to canonical OA references.

Implemented:

- `nex_oa.subjects`
- in-memory and SQLAlchemy subject registry repositories
- protected internal subject registry API routes
- PostgreSQL DDL for `oa_tenants` and `oa_subjects`
- `oa_subject_registry_snapshot.v1` contract schema and example
- regression tests for registry shape, auth, invalid refs/status, private
  identity payload rejection, and SQLite-backed repository behavior

## Boundary Decision

`nex-oa` is the logical owner of stable account references, but Slice 0193 does
not require a hard physical database split forever.

The recommended operating model remains:

- OA owns canonical subject ids:
  - `{type: "oa.tenant", id: "..."}`
  - `{type: "oa.user", id: "..."}`
- CX stores those ids as references for ownership and duplicate detection.
- AG can query or cache display/status metadata for operations views.
- Password login, external IdP mappings, roles, and full user profiles are
  explicitly deferred.

This preserves service ownership while leaving deployment topology flexible:
separate service databases can continue, or a future PostgreSQL deployment can
co-locate services under separate schemas if that is operationally simpler.

## API Shape

Protected by the existing mock service-token contract with audience `nex-oa`:

- `POST /internal/v1/subject-registry/ensure`
- `GET /internal/v1/subject-registry/tenants/{tenant_id}`
- `GET /internal/v1/subject-registry/tenants/{tenant_id}/subjects/{subject_id}`

The `ensure` endpoint is idempotent. It returns existing tenant/subject records
when the same stable ref already exists.

## Private Payload Policy

The registry stores only stable refs, display names, status, and safe metadata.
It rejects payload keys containing identity-secret hints such as passwords,
tokens, emails, phone numbers, raw profiles, authorization values, or secrets.

## Next Slice

Recommended next slice:

- `0194_cx_source_ownership_schema_migration`

That slice can add canonical `tenant_ref` and `owner_subject_ref` persistence to
CX while keeping the current legacy compatibility key intact.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_oa_subjects.py tests/test_database_schema_foundation.py tests/test_nex_cx_persistence_audit.py tests/test_nex_cx_processing_persistence.py tests/test_contract_validation.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
