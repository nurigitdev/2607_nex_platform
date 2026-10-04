# Slice 1303: Platform route and client topology inventory

## Outcome

- Inventoried 11 concrete HTTP client capability edges across seven logical
  platform edges from AE Web through AG.
- Confirmed there are no direct Python package imports between service-owned
  packages. Existing cross-service behavior uses explicit client ports.
- Confirmed AE API has HTTP clients for OA sessions and CX upload, retrieval,
  and generation; CX has separate MO embedding, reranking, and generation
  clients; AG has HTTP clients for readiness, generation audit, and artifacts.
- Identified four AG projection modules that can read service database URLs
  directly. These are historical operations adapters, not the accepted target
  state under `PLAT-FR-002` and the S131 non-drift rules.
- Recorded the missing canonical runtime topology manifest and duplicated
  service base-URL configuration as S132 refactoring candidates.

## Decision

The existing HTTP clients are reusable. Cross-service Python imports and
cross-service database reads remain prohibited. The AG database projection
adapters are retained during S131 for behavioral compatibility, but replacing
them with authenticated service API clients is the first P0 refactoring
candidate for S132.

No database or remote provider is required for this repository audit Slice.

## Verification

- Focused tests: `6 passed`.
- Slice Gate (`nex-ag`): `2,461 passed`.
- Coverage: statement `98.90%`, branch `96.53%`.
- Changed audit runner coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Audit summary: `11` concrete HTTP capabilities, `7` logical edges,
  `0` cross-service package imports, and `4` AG cross-service database
  coupling candidates.
