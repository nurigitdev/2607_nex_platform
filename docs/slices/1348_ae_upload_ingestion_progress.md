# Slice 1348: AE Upload Ingestion Progress

## Goal

Expose one authenticated, owner-scoped AE progress resource that joins the
durable upload handoff to CX ingestion-run and vector-freshness read models.

## Implementation

- Added `GET /api/v1/uploads/{upload_handoff_id}/progress` to AE API.
- Reads the upload handoff with tenant and owner filters before any CX call;
  another owner receives the same `404` as an absent handoff.
- Calls CX over the existing signed service-token and owner-context boundary.
- Projects queued, processing, retry, failure, cancellation, index-not-ready,
  and index-ready states without source, Markdown, chunk, vector, or credential
  payloads.
- Treats ingestion success as `INDEX_READY` only when CX reports the vector
  index as retrieval-usable and fresh.
- Published a strict JSON Schema and OpenAPI operation for the projection.

## Evidence

- Unit and branch tests cover route authorization, owner hiding, dependency
  failures, retry/failure states, malformed responses, HTTP propagation, and
  strict schema validation.
- Deterministic protected evidence proves owner access, cross-owner hiding,
  authentication denial, freshness, and private-payload exclusion.
- Actual PostgreSQL upload-to-index execution remains assigned to Slice `1350`.

## Verification

- Focused upload and document regression: `94 passed`.
- Slice Gate: `2,830 passed`, `5 skipped` protected PostgreSQL tests.
- Service statement coverage: `98.36%` (threshold `95%`).
- Service branch coverage: `96.27%` (threshold `94%`).
- `upload_progress.py`: statement `100%`, branch `100%`.
- Progress evidence runner: statement `100%`, branch `100%`, checks `12/12`.
- Contract validation: `159` schemas, `216` positive examples, `186`
  negative examples, and `7` OpenAPI documents.

## Result

Slice `1348` closes the restart-safe, owner-scoped progress gap. Slice `1349`
can now coordinate restart, recovery, cancellation, and cleanup against one
stable progress contract.
