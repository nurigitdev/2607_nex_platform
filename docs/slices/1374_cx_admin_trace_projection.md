# Slice 1374: CX Admin Trace Projection

## Goal

Expose CX ingestion, retrieval, and generation lifecycle stages to AG through a
service-API-only, metadata-safe trace projection.

## Implementation

- Added the reusable `service_cross_service_trace_projection.v1` contract and
  a shared source-projection builder.
- Added an AG-only CX internal operations route requiring `service:call`,
  `operations:read`, and `ADMIN` token admission.
- Added in-memory and SQLAlchemy trace sources over existing `cx_ingest_runs`,
  `cx_retrieval_packages`, and `cx_generation_executions` tables.
- Added trace indexes for ingestion and generation; the retrieval trace index
  already exists. No new table was introduced.
- Raw tenant/owner IDs and private payloads are replaced by a SHA-256 owner
  digest and strict allowlisted metadata.
- PostgreSQL execution is deferred to the protected S138 smoke in Slice 1380.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-cx \
  --test tests/test_nex_runtime_cross_service_trace.py \
  --test tests/test_nex_cx_trace_projection.py \
  --test tests/test_cx_trace_projection_contract.py \
  --coverage-target scripts/smoke/run_cx_trace_projection_contract.py \
  --smoke scripts/smoke/run_cx_trace_projection_contract.py
```

Expected evidence:

- authorized AG reads succeed while missing scope and non-AG callers fail;
- CX trace projection tests cover memory, SQLite, private-field redaction, and
  fail-closed database errors;
- contract validation reports `166` schemas, `225` examples, `193` negative
  examples, and `7` OpenAPI documents;
- evidence reports `checks=10/10`, `stages=3`, and `next=1375`.

Observed evidence:

- Slice Gate (`nex-cx`): `2,515 passed`.
- Repository statement coverage: `99.06%`.
- Repository branch coverage: `98.19%`.
- Shared trace builder, CX projection, and evidence runner focused
  statement/branch coverage: `100%`/`100%`.
- Contract validation: `166` schemas, `225` examples, `193` negative
  examples, and `7` OpenAPI documents.
- Evidence: `checks=10/10`, `stages=3`, `digests=3`, `next=1375`.
- SQLite exercised the SQLAlchemy adapter; actual PostgreSQL remains deferred
  to Slice 1380. No remote provider was contacted.
