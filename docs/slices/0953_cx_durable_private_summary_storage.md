# Slice 0953: CX Durable Private Summary Text Storage

## Goal

Replace the process-local-only summary payload boundary with an optional,
owner-scoped durable text adapter while retaining the existing lightweight
memory mode for deterministic regression tests.

## Implementation

- Reuses the S92 `CxPrivateTextStore` port and filesystem adapter rather than
  introducing a second summary-specific storage implementation.
- Injecting `private_summary_text_store` into `ContentIngestionStore` writes
  summary text under the canonical `summary_text` private payload kind.
- Tenant, owner subject, and summary identifiers determine a redacted storage
  key. Payload files remain immutable, UTF-8 encoded, owner scoped, and
  SHA-256 verified.
- Summary metadata replaces its former `memory://` reference with a
  `cx-private://filesystem-text-v1/...` URI before metadata persistence.
- The in-process dictionary is only a cache in durable mode. Clearing it and
  recreating the filesystem adapter reloads and verifies the payload.
- PostgreSQL continues to receive metadata, hashes, and the private URI only;
  raw summary text never enters a public metadata record.
- The deployment root remains `NEX_CX_PRIVATE_TEXT_STORAGE_ROOT`, defaulting to
  `/data/nex-platform/cx/private-text`, as frozen in S92.

The adapter is opt-in in this Slice. Production composition and the complete
document-intelligence API are scheduled for Slice 0957. PostgreSQL and remote
providers are not required here.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_document_summary_storage.py \
  --cov=nex_cx.document_summary_storage \
  --cov=run_cx_document_summary_storage_smoke \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_document_summary_storage_smoke.py --summary
```

Observed on 2026-09-22:

- Focused durable-storage suite: `11 passed`; new module and evidence runner
  statement/branch coverage: 100%/100%.
- Deterministic storage evidence: `8/8 PASS`, including owner isolation and
  reload after adapter recreation.
- Full regression: `7186 passed`, statement coverage `98.88%`, branch coverage
  `96.57%`.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.
- Full quality gate completed with exit code `0`.
