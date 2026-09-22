# Slice 0958: CX Document Intelligence Observability and Contracts

## Goal

Close the final S96 deterministic implementation gap with metadata-only
document-intelligence events and explicit raw-safe API response contracts.

## Implementation

- Adds deterministic `ready`, `similarity_observed`, and `failed` operational
  events for owner-authorized document-intelligence requests.
- Emits status, hashes, model lineage, vector dimension, freshness, candidate
  count, error code, and correlation metadata only. Raw summary text, bounded
  previews, storage URIs, candidate payloads, and vectors never enter event
  details.
- Keeps authentication and cross-owner not-found responses silent so event
  records cannot disclose the existence of another owner's document.
- Treats operational-event persistence as best effort and returns a bounded
  observability result without breaking the primary API operation.
- Adds strict JSON Schemas, positive examples, and negative raw-summary/vector
  fixtures for both document-intelligence responses.
- Binds the two successful OpenAPI responses to explicit component schemas.
- Resolves the final `document_intelligence_observability_missing` item in the
  S96 boundary audit.

This Slice is deterministic and does not connect to PostgreSQL or DGX. Actual
database plus live generation and embedding evidence remains Slice 0959.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_document_intelligence_observability.py \
  tests/test_nex_cx_document_intelligence_orchestration.py \
  tests/test_nex_cx_document_intelligence_contracts.py \
  tests/test_cx_document_intelligence_contract_observability.py \
  --cov=nex_cx.document_intelligence_observability \
  --cov=nex_cx.document_intelligence_orchestration \
  --cov=run_cx_document_intelligence_contract_observability \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_document_intelligence_contract_observability.py \
  --summary
./.venv/bin/python scripts/quality/validate_contracts.py
```

Observed on 2026-09-22:

- Focused observability, API, contract, and evidence suite: `25 passed`;
  targeted modules reached `100%` statement and branch coverage.
- Deterministic metadata-only evidence: `10/10` checks passed.
- S96 boundary audit: all `7` historical gaps resolved, `0` open.
- Contract validation: `87` schemas, `138` positive examples, `103` negative
  examples, and `7` OpenAPI documents passed.
- Full regression: `7313 passed`.
- Full coverage: statement `98.90%`, branch `96.59%`.
- Full quality gate completed with exit code `0`.
