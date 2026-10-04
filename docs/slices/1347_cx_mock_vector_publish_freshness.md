# Slice 1347: CX mock vector publish freshness

## Outcome

- Routed chunk embedding through the protected NeX-MO mock embedding API with
  a CX service token and the canonical `mock-embedding-default` alias.
- Preserved owner identity in the deterministic vector-index manifest and
  private payload keys.
- Added payload-backed freshness verification immediately after vector publish.
- Added the same verification before an existing READY manifest is reused, so
  missing or changed payloads cannot be reported as index-ready.
- Kept source text, chunk text, vectors, tokens, and storage paths out of
  evidence.

## Guardrails

- READY requires a matching source snapshot, embedding profile, payload count,
  and payload fingerprint with `retrieval_usable=true`.
- A READY manifest with missing or inconsistent payloads fails closed with the
  retryable `cx.mvp_ingestion.vector_index_not_fresh` worker error.
- An unavailable payload snapshot fails with the retryable
  `cx.mvp_ingestion.vector_freshness_unavailable` error.
- Owner-mismatched manifest reads remain indistinguishable from not found.
- No remote embedding provider, PostgreSQL database, table, or migration was
  required. The actual PostgreSQL journey remains assigned to Slice 1350.

## Verification

- Focused regression covers publish, protected MO mock admission, READY reuse,
  stale payload rejection, unavailable freshness state, ownership isolation,
  and privacy-safe evidence: `161 passed` before branch-hardening additions and
  `22 passed` with both changed scopes at `100.00%` statement/branch coverage.
- CX Slice Gate: `2,292 passed`, statement coverage `99.07%`, and branch
  coverage `98.18%`.
- The indexer and deterministic evidence runner each reached `100.00%`
  statement and branch coverage.
- Contract validation passed with `158` schemas, `216` positive examples,
  `186` negative examples, and `7` OpenAPI documents.
- Deterministic evidence passed `12/12` checks with three chunks, freshness
  `READY`, and `next=1348`.
