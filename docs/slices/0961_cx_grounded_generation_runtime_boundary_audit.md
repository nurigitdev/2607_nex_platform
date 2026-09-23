# Slice 0961: CX Grounded Generation Runtime Boundary Audit

## Goal

Freeze the S97 owner-private grounded-generation runtime boundary before
changing provider prompts, persistence, or API behavior.

## Findings

- CX already authenticates the tenant and owner, validates the referenced
  retrieval package and selected evidence, applies the retrieval-quality guard,
  calls NeX-MO, builds a structured draft, and validates citation labels.
- The public generation metadata table and owner index already exist, and the
  persistence sanitizer rejects private prompt/output fields.
- The active generation model is `Qwen3.5-4B` through the DGX endpoint on port
  `9111`.
- The runtime still uses the process-global `GenerationExecutionStore`; public
  execution records, drafts, citations, and progress disappear on restart.
- The MO payload forwards AE prompt/messages and hashes them, but CX does not
  yet assemble the authorized retrieval evidence into a canonical untrusted
  context envelope.
- Provider output is treated as plain text with `[n]` citation extraction. It
  lacks a strict provider-output normalization contract before draft creation.
- Full generated output has no owner-scoped durable private payload reference.
- Idempotent admission, restart-safe read projection, generation-specific
  operational events, and a protected PostgreSQL/live-provider proof remain
  open.

## Decision

- Keep the current bounded synchronous HTTP facade for S97 and make it
  idempotent with durable write-through. Asynchronous worker and streaming
  transport remain explicit later extensions.
- CX, not AE or MO, assembles the provider prompt from the owner-admitted READY
  retrieval package. Retrieved text is marked as untrusted context.
- Public PostgreSQL rows contain metadata, hashes, owner lineage, citations,
  and validation outcomes only. Full generated text uses an owner-scoped
  durable private payload reference.
- Citation validation must fail closed against the exact retrieval package and
  selected evidence set before a grounded response is reported successful.
- Slices 0961-0968 are deterministic and mock-first. Slice 0969 requires the
  actual `nex_cx_test` database and the live generation provider.

## Slice Plan

1. Slice 0961: boundary audit and refactoring checkpoint.
2. Slice 0962: canonical grounded prompt package and evidence binding.
3. Slice 0963: provider output normalization and citation validation.
4. Slice 0964: durable owner-private generated-output storage.
5. Slice 0965: SQL generation runtime repository and migration.
6. Slice 0966: idempotent bounded grounded-execution runtime.
7. Slice 0967: restart-safe owner-scoped generation read model.
8. Slice 0968: operations observability and contract hardening.
9. Slice 0969: actual PostgreSQL plus live DGX generation smoke.
10. Slice 0970: S97 closure.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_grounded_generation_runtime_boundary_audit.py \
  --cov=run_cx_grounded_generation_runtime_boundary_audit \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_grounded_generation_runtime_boundary_audit.py \
  --summary
```

PostgreSQL and DGX are intentionally not invoked in this audit Slice.

Observed result:

- focused boundary audit: `5 passed`, statement `100%`, branch `100%`
- related generation/draft/persistence regression: `84 passed`
- boundary summary: `PASS`, foundations `5`, gaps `8`, open `8`, issues `0`
- full regression: `7,333 passed`
- full statement coverage: `98.89%`
- full branch coverage: `96.60%`
- contract validation: `87` schemas, `138` examples, `103` negative
  examples, and `7` OpenAPI documents
- quality gate exit status: `0`
