# Slice 0964: CX Durable Private Generation Output

## Goal

Persist full generated text outside the public generation projection through an
owner-scoped durable private payload reference.

## Implementation

- Added `generation_output` to the supported private text payload kinds.
- Added a generated-output storage adapter that reuses the existing immutable,
  atomic, owner-scoped filesystem text store.
- Bound each private payload to the CX generation ID and expected SHA-256.
- Added restart-safe reload with hash and byte-size verification.
- Kept public metadata raw-safe: schema version, opaque storage URI, backend,
  SHA-256, and byte size only.
- Added a dedicated default root at
  `/data/nex-platform/cx/generated-outputs`, configurable through
  `NEX_CX_GENERATION_OUTPUT_STORAGE_ROOT`.
- Kept PostgreSQL repository and production route wiring in Slice 0965.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_generation_private_output.py \
  tests/test_nex_cx_private_content.py \
  tests/test_nex_cx_private_text_store.py \
  tests/test_cx_grounded_generation_runtime_boundary_audit.py \
  --cov=nex_cx.generation_private_output --cov=nex_cx.private_content \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_grounded_generation_runtime_boundary_audit.py \
  --summary
```

PostgreSQL and DGX are intentionally not invoked in this deterministic Slice.

Observed result:

- focused private-output/private-store regression: `93 passed`
- generated-output adapter coverage: statement `100%`, branch `100%`
- expanded generation/persistence/private-storage regression: `222 passed`
- S97 boundary summary: `PASS`, gaps `8`, open `5`, issues `0`
- final full regression: `7,424 passed`
- full statement coverage: `98.90%`
- full branch coverage: `96.61%`
- contract validation: `87` schemas, `138` examples, `103` negative
  examples, and `7` OpenAPI documents
- quality gate exit status: `0`
