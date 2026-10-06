# Slice 1376: OA and MO Trace Projections

## Goal

Expose OA authentication/trust and MO provider execution stages to AG through
service-owned, ADMIN-scoped, metadata-only APIs.

## Implementation

- Added the common internal operations route to OA and MO, requiring
  `service:call`, `operations:read`, ADMIN admission, and caller `nex-ag`.
- OA combines existing `oa_auth_events` with OA-owned operational trust events,
  hashes user ownership, and exposes only authentication lifecycle metadata.
- Added an OA trace index; no OA domain table was introduced.
- MO now records provider request success/failure into the existing durable
  `service_operational_events` store and projects only capability, alias,
  model revision, deployment, route, mode, retryability, result, and opaque
  provider-request identity.
- Reused MO's existing operational-event trace index; no MO migration or new
  table was required.
- Registered the MO internal trace route in OpenAPI and advanced the guarded
  runtime/OpenAPI operation inventory from `31/31` to `32/32` with zero drift.
- Moved provider trace-event composition into `provider_trace.py`, preserving
  the existing `providers.py` 550-line architecture budget and S112 audit.
- Expanded the strict trace attribute allowlist for model-agnostic provider
  identity without admitting URLs, credentials, prompts, outputs, or raw
  provider payloads.

Remote provider access is not required for this slice. Actual test PostgreSQL
and provider-connected evidence remains assigned to Slice 1380.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_runtime_cross_service_trace.py \
  --test tests/test_nex_oa_trace_projection.py \
  --test tests/test_oa_mo_trace_projection_contract.py \
  --coverage-target scripts/smoke/run_oa_mo_trace_projection_contract.py \
  --smoke scripts/smoke/run_oa_mo_trace_projection_contract.py

scripts/quality/run_slice_gate.sh \
  --service nex-mo \
  --test tests/test_nex_runtime_cross_service_trace.py \
  --test tests/test_nex_mo_trace_projection.py \
  --test tests/test_oa_mo_trace_projection_contract.py \
  --coverage-target scripts/smoke/run_oa_mo_trace_projection_contract.py \
  --smoke scripts/smoke/run_oa_mo_trace_projection_contract.py
```

Expected evidence:

- OA and MO reject missing scope and non-AG callers;
- provider routes durably emit redacted success/failure trace events;
- memory and SQLite paths, source failures, owner redaction, provider identity,
  and forbidden provider URL cases are covered;
- contract validation reports `166` schemas, `228` examples, `196` negative
  examples, and `7` OpenAPI documents;
- evidence reports `checks=14/14`, `stages=2+1`, and `next=1377`.

Observed evidence:

- OA Slice Gate: `1001 passed`, `11 skipped`; statement `98.46%`, branch
  `97.81%`; focused evidence statement/branch `100%`.
- MO Slice Gate: `1113 passed`, `6 skipped`; statement `99.84%`, branch
  `99.24%`; focused evidence statement/branch `100%`.
- Contract validation: `166` schemas, `228` examples, `196` negative examples,
  and `7` OpenAPI documents.
- Deterministic evidence: `checks=14/14`, `stages=2+1`, `digests=1`,
  `next=1377`.
