# Slice 1072: AE Asynchronous Artifact Rendering Boundary Audit

## Goal

Freeze the S108 ownership, persistence, queue, source-lineage, privacy, and
compatibility boundary before AE moves artifact rendering out of the request
transaction and into durable worker execution.

## Findings

- AE already owns artifact metadata, render jobs, rendered-file metadata,
  preview/download links, and private rendered payload storage.
- The current render POST fetches the CX structured draft, transforms all
  formats, stores payloads, and persists a `COMPLETED` render job inline.
- `ae_artifact_render_jobs` already supports queued, running, terminal, progress,
  failure, and retry metadata, while the common `service_jobs` table and queue
  provide durable admission and worker claiming.
- S107 provides owner-safe generated-response and chat lineage that can be
  referenced by render admission without copying response content into jobs or
  operational evidence.

## Frozen Decisions

- AE remains the artifact rendering system of record. CX remains the owner of
  the validated structured draft used as render source content.
- Async render state uses `ae_artifact_render_jobs`; execution admission uses
  the existing `service_jobs` queue. S108 plans no new table.
- Rendered bytes stay behind the AE private storage adapter and remain outside
  PostgreSQL, public API metadata, workspace activity, and operational events.
- The existing synchronous render route remains available for compatibility.
  New clients use an explicit asynchronous admission contract.
- Async status, cancellation, retry, and result access require exact tenant and
  owner scope derived from the owning artifact.
- The worker performs deterministic local MD, HTML, DOCX, and PDF transforms.
  A remote embedding, reranking, or generation provider is not required.
- Slice 1080 must prove durable queue and render recovery against the actual
  `nex_ae_test` database and an isolated private-storage directory.

## Slice Plan

1. `1072`: boundary audit and refactoring checkpoint.
2. `1073`: asynchronous render contract and state machine.
3. `1074`: durable queue admission and render-job persistence.
4. `1075`: exact-owner async admission, status, and cancellation API.
5. `1076`: artifact render worker execution and Checkpoint Gate.
6. `1077`: generated-response and chat-to-artifact lineage integration.
7. `1078`: retry, restart recovery, and metadata-only observability.
8. `1079`: JSON Schema and OpenAPI hardening.
9. `1080`: actual PostgreSQL and private-storage smoke evidence.
10. `1081`: S108 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_artifact_rendering_boundary_audit.py \
  --coverage-target scripts/smoke/run_ae_async_artifact_rendering_boundary_audit.py \
  --smoke scripts/smoke/run_ae_async_artifact_rendering_boundary_audit.py
```

The audit performs no database mutation, private payload write, or provider
call.

## Observed Evidence

- Slice Gate: `2490 passed`, `4 skipped` protected PostgreSQL tests.
- Coverage: statement `98.01%`, branch `95.96%`.
- Boundary runner coverage: statement `100.00%`, branch `100.00%`.
- Contracts: schemas `103`, examples `161`, negative examples `124`,
  OpenAPI documents `7`.
- Audit: foundations `6`, gaps `8`, open `8`, issues `0`, next `1073`.
