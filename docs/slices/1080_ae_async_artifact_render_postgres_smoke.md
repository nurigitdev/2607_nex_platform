# Slice 1080: AE Asynchronous Artifact Render PostgreSQL Smoke

## Goal

Prove the S108 durable asynchronous artifact-render path against the actual AE
test PostgreSQL database and an isolated private rendered-payload directory.

## Evidence Boundary

- The protected smoke is opt-in through
  `NEX_AE_ASYNC_ARTIFACT_RENDER_POSTGRES_SMOKE=1` and rejects every database or
  role except `nex_ae_user@nex_ae_test`.
- AE migrations must be current before the probe can execute.
- The probe creates a real artifact, persists the render admission in
  `ae_artifact_render_jobs` and `service_jobs`, reconstructs stores after a
  simulated process restart, and executes the render worker.
- Rendered MD and HTML bytes are read back from an isolated local private
  storage adapter. PostgreSQL is checked for metadata only.
- A second render fails once with a retryable CX dependency error, persists its
  bounded retry, introduces deterministic render/queue state drift, and proves
  reconciliation back to the retry state.
- Exact-owner API reads succeed while a different owner receives `404`.
- Probe rows and temporary payload files are removed before PASS evidence is
  returned.
- Remote generation, embedding, and reranking providers are not required; the
  artifact transforms are deterministic local operations.

## Verification

```bash
NEX_AE_ASYNC_ARTIFACT_RENDER_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' \
./.venv/bin/pytest -q tests/test_ae_async_artifact_render_postgres_smoke.py

scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_artifact_render_postgres_smoke.py \
  --test tests/test_ae_async_artifact_render_worker.py \
  --test tests/test_ae_async_artifact_render_recovery.py \
  --coverage-target scripts/smoke/run_ae_async_artifact_render_postgres_smoke.py
```

The normal Slice Gate leaves the destructive protected test skipped. The first
command is the required non-skipped PostgreSQL evidence run.

## Observed Evidence

- Protected PostgreSQL suite: `8 passed`, with the actual smoke test executed
  rather than skipped.
- Protected runner: `PASS`, `15` checks, `7` probe rows observed, and `0`
  rows remaining after cleanup.
- Database identity: `nex_ae_user@nex_ae_test`.
- Slice Gate: `PASS` (`2663 passed`, `5 skipped` protected PostgreSQL tests).
- Overall statement coverage: `98.04%`.
- Overall branch coverage: `96.10%`.
- Smoke runner coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `108` schemas, `166` examples, `129` negative
  examples, and `7` OpenAPI documents.
