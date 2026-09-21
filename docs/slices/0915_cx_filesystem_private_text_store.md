# Slice 0915: CX filesystem private text persistence adapter

## Goal

Provide restart-safe local persistence for owner-scoped chunk and summary text
through the Slice 0914 `CxPrivateTextStore` port.

## Implementation

- `FileSystemCxPrivateTextStore` stores UTF-8 payloads outside PostgreSQL.
- The default root is `/data/nex-platform/cx/private-text`; deployments can set
  `NEX_CX_PRIVATE_TEXT_STORAGE_ROOT`.
- Tenant, subject, and content identifiers are SHA-256-derived before they
  become path or URI segments.
- Directories use private permissions and published payload files use `0600`.
- A complete temporary file is atomically hard-linked into its immutable final
  location. Repeated identical writes are idempotent; content-id reuse with a
  different payload fails with `409`.
- Reads after adapter recreation verify UTF-8 and SHA-256 integrity. Cross-owner
  operations retain the not-found response boundary.
- Receipts contain metadata only and use `cx-private://filesystem-text-v1/...`
  URIs; absolute paths and private text remain internal.

This adapter is deliberately independent of CX ingestion orchestration. Runtime
composition and metadata linkage continue in Slice 0916. PostgreSQL and DGX are
not required by this slice.

## Verification

```text
filesystem text smoke: PASS (8/8 checks)
focused tests: 21 passed; statement 100%; branch 100%
aggregate regression: 6437 passed
aggregate statement coverage: 76768/77649 (98.86540715269997%)
aggregate branch coverage: 17790/18440 (96.47505422993493%)
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI documents
```
