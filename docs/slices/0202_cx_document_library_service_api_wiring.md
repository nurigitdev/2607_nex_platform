# Slice 0202: CX Document Library Service API Wiring

## Scope

Slice 0202 wires the Slice 0201 owner-scoped document library projection into
the CX service API.

Implemented:

- `GET /api/v1/documents` returns active documents for one tenant/user owner
  scope.
- service-claim authentication is enforced with the existing CX
  `DEFAULT_SERVICE_SCOPE` policy.
- query validation maps to `cx.document_library_query_invalid`.
- repository failures map to retryable `application/problem+json` responses.
- CX runtime wiring passes persistence source metadata into the projection.
- `nex-cx.openapi.yaml` documents the new list endpoint.

## Query Parameters

```text
tenant_id       legacy alias for tenant_ref.id; defaults to local-tenant
owner_user_id   legacy alias for owner_subject_ref.id; defaults to local-user
limit           bounded to 1-100
```

The endpoint still filters through canonical owner ref columns in the
repository:

```text
tenant_ref_type/id
owner_subject_ref_type/id
lifecycle_status = ACTIVE
```

## Privacy Boundary

The route returns the same raw-safe projection as Slice 0201. It does not expose
raw source, extracted Markdown, summary body, embedding vectors, local storage
paths, provider secrets, or database passwords.

## Next Slice

Recommended next slice:

- `0203_cx_document_library_postgresql_smoke_evidence`

That slice should run the new route against the real `nex_cx_test` database.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_document_library.py tests/test_contract_validation.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
28 passed
```

Observed full quality gate:

```text
1567 passed
statement_coverage=97.87%
branch_coverage=93.51%
contract_validation=pass schemas=45 examples=74 negative_examples=50 openapi=7
```
