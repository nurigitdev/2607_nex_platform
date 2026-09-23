# Slice 0968: CX Generation Observability and Contract Hardening

## Goal

Make terminal grounded-generation outcomes operationally visible without
copying owner-private prompts, evidence, generated text, storage locations, or
credentials into operational events, and freeze the restart-safe read APIs as
explicit contracts.

## Implementation

- Added deterministic metadata-only events for completed, failed, replayed,
  and durable-read failure outcomes.
- Events expose only status, provider alias/capability, compatibility and
  grounding flags, evidence counts, finish reason, output hash/size, bounded
  usage counts, and safe failure classification.
- Kept event emission best-effort so an operational event store failure cannot
  change a generation response.
- Wired terminal observations after durable or in-memory persistence and wired
  request/read failures only after owner authentication.
- Hardened the generation metadata projection with explicit top-level and
  nested allowlists. Storage URI/backend, output preview, provider endpoint,
  raw prompt, and unknown future fields cannot pass through the read model.
- Made the memory-mode generation GET return the same safe read-model shape as
  the PostgreSQL-mode GET.
- Added strict JSON Schemas, positive and negative fixtures, and OpenAPI 200
  response bindings for generation metadata and explicit owner-private
  content.
- Corrected the final protected-live gap key in the S97 boundary audit. With
  0968 complete, Slice 0969 is now selected automatically.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_generation_observability.py \
  tests/test_nex_cx_generation_read_model.py \
  tests/test_cx_grounded_generation_runtime_boundary_audit.py \
  --cov=nex_cx.generation_observability \
  --cov=nex_cx.generation_read_model \
  --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
./scripts/quality/run_quality_gate.sh
```

- Focused observability/read-model regression: `23 passed`; both changed
  runtime modules reached `100%` statement and branch coverage.
- Expanded generation/read-model regression: `68 passed`.
- Full regression: `7,479 passed`.
- Full statement coverage: `98.89%`.
- Full branch coverage: `96.61%`.
- Contract validation: `89` schemas, `140` examples, `105` negative cases,
  and `7` OpenAPI documents.
- S97 boundary audit: `pass`, eight gaps tracked, one protected-live gap open,
  with Slice 0969 selected next.
- Quality gate exit status: `0`.

Actual PostgreSQL persistence and DGX provider execution remain intentionally
reserved for Slice 0969.
