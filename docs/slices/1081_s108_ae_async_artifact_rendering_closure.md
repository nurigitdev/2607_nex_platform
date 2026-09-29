# Slice 1081: S108 AE Asynchronous Artifact Rendering Closure

## Goal

Close S108 with machine-checkable evidence that artifact rendering is durably
queued, exact-owner scoped, restart-safe, retry-safe, privacy-safe, and linked
to its generated-response and structured-draft lineage.

## Closure

- AE remains the artifact and render lifecycle system of record while CX owns
  the validated structured draft used as render source.
- `ae_artifact_render_jobs` stores render lifecycle metadata and the common
  `service_jobs` queue stores durable worker admission. No table was added.
- Exact tenant and owner scope protects async admission, status, cancellation,
  recovery, and reconciliation routes.
- Worker execution performs deterministic local transforms, publishes files
  idempotently, observes cancellation, and survives process restart.
- Generated-response lineage can be validated at admission without placing
  response content in queue payloads or render projections.
- Bounded retry remains owned by the common JobQueue; reconciliation repairs
  safe queue/render state drift while dead letters require manual review.
- Rendered bytes remain in AE private storage. PostgreSQL, public lifecycle
  responses, and recovery evidence contain metadata only and never expose a
  storage path.
- Canonical JSON Schemas, positive and negative fixtures, and AE OpenAPI 1.6
  freeze the asynchronous lifecycle and recovery surface.
- Actual `nex_ae_test` evidence proves migration currency, durable admission,
  restart execution, private MD/HTML payloads, owner isolation, retry,
  reconciliation, and zero probe residue.
- The synchronous render route remains compatible. Remote generation,
  embedding, and reranking providers are not required for local transforms.

## Verification

```bash
NEX_AE_ASYNC_ARTIFACT_RENDER_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<AE test database URL>' \
./.venv/bin/python \
  scripts/smoke/run_s108_ae_async_artifact_rendering_closure.py --summary

scripts/quality/run_quality_gate.sh
```

## Observed Evidence

- Protected closure against the actual `nex_ae_test` PostgreSQL database:
  `10/10` components, `8/8` gaps, and `15` PostgreSQL checks passed; next is
  `S109`.
- Full Gate: `8,724 passed`, `5 skipped`; statement coverage `98.80%` and
  branch coverage `96.84%`.
- Contract Gate: `108` schemas, `166` positive examples, `129` negative
  examples, and `7` OpenAPI documents passed validation.
- Full Gate registered the protected PostgreSQL probe as intentionally skipped
  without its opt-in environment variable, then passed the S108 closure with
  `10/10` components and `8/8` gaps. The protected run above supplies the
  required actual-database evidence.
