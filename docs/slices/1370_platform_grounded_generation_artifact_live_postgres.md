# Slice 1370: Platform Grounded Generation Artifact Live PostgreSQL

## Outcome

- Executed one OA-authenticated browser journey through AE Web/API, CX, MO,
  PostgreSQL, grounded generation, citation validation, AE response lineage,
  artifact admission, restart-safe rendering, preview, and download.
- Adopted structured-draft persistence recommendation A. CX stores the full
  draft in owner-private storage and persists only its SHA-256, byte size,
  backend/schema version, and opaque `cx-private://` reference in PostgreSQL.
- Added restart-safe owner-scoped structured-draft readback with hash, size,
  schema, generation-id, and draft-id verification. Public generation metadata
  does not expose the private storage reference.
- Preserved model independence: the durable contract records provider/model
  lineage supplied by MO but does not make CX draft persistence dependent on a
  particular generation, embedding, or reranker model.
- Hardened canonical retrieval-package identity propagation where PostgreSQL
  promotes the package id from request metadata to the execution record.
- Added protected evidence that fails closed unless the test profile, both
  service test databases, all three live provider capabilities, and cleanup
  checks succeed.

## Storage Decision

The structured draft is private generated content, not an operational database
record. CX therefore owns its bytes in the same owner-private storage boundary
as other generated payloads. PostgreSQL owns only integrity and lookup
metadata:

- `structured_draft_storage_backend`
- `structured_draft_storage_uri`
- `structured_draft_sha256`
- `structured_draft_size_bytes`
- `structured_draft_private_schema_version`

The URI is opaque outside CX. A caller must pass CX service admission and the
exact tenant/owner scope before CX resolves it. Missing payloads, cross-owner
access, hash or size drift, malformed JSON, and lineage mismatch all fail
closed. This layout permits a future object-storage adapter without changing
the PostgreSQL read model or AE contract.

## Protected Evidence

The actual protected execution completed with:

- checks: `8/8 PASS`
- actual databases: `nex_ae_test` and `nex_cx_test`
- live capabilities: embedding, reranking, and generation (`3/3`)
- browser evidence: one correlated authenticated request
- artifact state: `READY`; render job state: `COMPLETED`
- rendered files: `2`; owner preview/download: PASS
- cross-owner read: hidden with owner-scoped not-found semantics
- PostgreSQL private payload exposure: false
- cleanup: AE and CX journey rows `0`; temporary artifact storage absent

Provider credentials, database credentials, endpoint URLs, prompts, source
text, generated text, structured-draft bytes, vectors, and absolute storage
paths are intentionally excluded from committed evidence.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_platform_grounded_generation_artifact_live_postgres_smoke.py \
  tests/test_ae_web_grounded_generation_playwright_postgres_smoke.py \
  tests/test_nex_cx_generation_structured_draft.py \
  tests/test_nex_cx_generation_read_model.py \
  tests/test_nex_ae_generated_response_lineage.py \
  tests/test_nex_ae_artifacts.py

scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_platform_grounded_generation_artifact_live_postgres_smoke.py \
  --test tests/test_nex_cx_generation_structured_draft.py \
  --test tests/test_nex_cx_generation_read_model.py \
  --test tests/test_nex_ae_generated_response_lineage.py \
  --test tests/test_nex_ae_artifacts.py \
  --coverage-target \
    scripts/smoke/run_platform_grounded_generation_artifact_live_postgres_smoke.py \
  --smoke \
    scripts/smoke/run_platform_grounded_generation_artifact_live_postgres_smoke.py
```

The protected runner is enabled separately with
`NEX_S137_GROUNDED_ARTIFACT_LIVE_POSTGRES_SMOKE=1` and operator-injected test
database/provider configuration. Ordinary regression and Full Gate runs leave
it safely skipped.

Final verification results:

- Slice Gate: `2,701 passed`, `123` dependency warnings
- CX Slice coverage: statement `99.06%`, branch `98.20%`
- protected live runner and structured-draft persistence coverage: statement
  `100%`, branch `100%` for both changed scopes
- contract validation: `163` schemas, `222` positive examples, `190` negative
  examples, and `7` OpenAPI documents
- protected journey: `8/8` checks, `3/3` live capabilities, `2/2` actual test
  databases, and zero AE/CX row or temporary-file residue

Slice 1371 owns the operator runbook, closure evidence, Full Gate, and S138
handoff. It must not repeat protected mutation by default.
