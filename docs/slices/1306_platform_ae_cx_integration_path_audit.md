# Slice 1306: Platform AE-to-CX integration path audit

## Outcome

- Inventoried eight AE API HTTP clients for CX upload, document, retrieval,
  synchronous generation, asynchronous generation, recovery, repaired response,
  and artifact-source capabilities.
- Confirmed every client sends an audience-bound AE service token, owner scope,
  request ID, and trace context. Asynchronous generation also sends an explicit
  idempotency key.
- Confirmed the five core CX upload/document/retrieval/generation/async routes
  exist and AE does not reference the CX database URL.
- Confirmed browser upload ownership is overwritten from authenticated browser
  context before handoff to CX.
- Identified duplicated transport configuration across the eight clients as an
  S132 consolidation candidate.
- Identified `local-tenant` and `local-user` owner fallbacks in the shared AE CX
  owner helper. They are useful for deterministic mock regression but are not
  accepted for protected signed-service profiles, which must fail closed.

## Decision

The AE-to-CX HTTP boundary is reusable and database sharing remains prohibited.
S132 should centralize transport configuration without merging domain clients.
S134/S135 must remove owner fallback behavior from protected profiles and prove
an actual OA-claimed upload-to-generation path on service test databases.

No database or remote provider is required for this repository audit Slice.

## Verification

- Focused tests: `5 passed`.
- Checkpoint Gate: `10,275 passed`, `24 skipped` protected smokes.
- Coverage: statement `98.89%`, branch `97.20%`.
- Changed audit runner coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Audit summary: `8` AE-to-CX clients, `5` core CX routes, `0` AE reads
  of the CX database URL, and one protected-profile owner-fallback risk.
