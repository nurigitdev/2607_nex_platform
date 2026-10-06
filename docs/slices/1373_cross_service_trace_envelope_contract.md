# Slice 1373: Cross-Service Trace Envelope Contract

## Goal

Define one metadata-only trace-stage envelope for OA, AE, CX, MO, and AG, plus
the ordered AG timeline projection that will compose those service API results.

## Implementation

- Added `cross_service_trace_stage.v1` with strict service, family, status,
  timestamp, opaque correlation-reference, owner-digest, and safe-attribute
  allowlists.
- Added `ag_cross_service_trace_e2e.v1` with source readiness, ordered stages,
  count summaries, and explicit private-payload exclusion.
- Added shared runtime builders that reject private/free-text keys, unsafe
  identifiers, missing timezones, unknown sources, and cross-trace stages.
- Registered positive and negative examples and a deterministic evidence runner.
- This Slice does not create a table or contact PostgreSQL or model providers.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-ag \
  --test tests/test_nex_runtime_cross_service_trace.py \
  --test tests/test_platform_trace_envelope_contract.py \
  --coverage-target scripts/smoke/run_platform_trace_envelope_contract.py \
  --smoke scripts/smoke/run_platform_trace_envelope_contract.py
```

Expected evidence:

- runtime and evidence runner statement/branch coverage remain at or above the
  repository Slice Gate thresholds;
- contract validation reports `165` schemas, `224` examples, `192` negative
  examples, and `7` OpenAPI documents;
- evidence reports `next=1374` and no private payload admission.

Observed evidence:

- Slice Gate (`nex-ag`): `2,490 passed`.
- Repository statement coverage: `98.88%`.
- Repository branch coverage: `96.47%`.
- Trace runtime and evidence runner focused statement/branch coverage:
  `100%`/`100%`.
- Contract validation: `165` schemas, `224` examples, `192` negative
  examples, and `7` OpenAPI documents.
- Evidence: `checks=12/12`, `stages=1`, `contracts=2`, `next=1374`.
- No database or remote provider was contacted.
