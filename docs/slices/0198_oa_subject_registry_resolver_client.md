# Slice 0198: OA Subject Registry Resolver Client

## Scope

Slice 0198 adds a shared OA subject registry resolver client foundation for
AE/CX ownership workflows.

Implemented:

- shared `nex_runtime.subject_resolver` module.
- `HttpSubjectRegistryResolver` for OA subject registry `ensure` and read-only
  verification calls.
- resolver normalization for `cx_source_ownership_ref.v1` ownership refs.
- service-token, request id, traceparent, and caller service header propagation.
- safe error mapping for OA problem responses, non-object JSON, malformed JSON,
  and transport failures.
- environment-based resolver construction with `NEX_OA_BASE_URL`,
  `NEX_AE_TO_OA_SERVICE_TOKEN`, `NEX_CX_TO_OA_SERVICE_TOKEN`, and
  `NEX_OA_SUBJECT_RESOLVER_TIMEOUT_SECONDS`.

## Compatibility

The resolver does not change AE or CX route behavior yet. It only provides a
tested client boundary for the next slices.

Read-only resolution calls:

```text
GET /internal/v1/subject-registry/tenants/{tenant_id}
GET /internal/v1/subject-registry/tenants/{tenant_id}/subjects/{subject_id}
```

Ensure resolution calls:

```text
POST /internal/v1/subject-registry/ensure
```

If `uploaded_by_subject_ref` equals `owner_subject_ref`, the resolver avoids a
duplicate subject registry call.

## Privacy Boundary

The resolver accepts only `tenant_ref`, `owner_subject_ref`, and
`uploaded_by_subject_ref` types and IDs. Unsupported ownership envelope fields
and unsupported subject-ref fields are rejected before any OA call.

## Next Slice

Recommended next slice:

- `0199_ae_upload_ownership_resolver_wiring`

That slice should wire AE upload intake to this resolver behind a guarded
runtime setting before the CX upload request is sent.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_subject_resolver.py tests/test_nex_oa_subjects.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
