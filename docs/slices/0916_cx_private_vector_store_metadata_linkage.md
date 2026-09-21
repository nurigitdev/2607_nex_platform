# Slice 0916: CX private vector adapter and metadata linkage

## Goal

Provide a replaceable, restart-safe local implementation of `CxVectorStore`
and bind private vector receipts to public CX embedding metadata without
exposing vector values.

## Refactoring

The immutable digest path, private permissions, atomic publish, integrity
check, and filesystem error mapping introduced by Slice 0915 now live in the
internal `ImmutableOwnerScopedFileStorage`. Text and vector adapters share this
single implementation instead of duplicating security-sensitive file logic.

## Implementation

- `FileSystemCxVectorStore` persists canonical JSON vector envelopes under
  `/data/nex-platform/cx/private-vectors` by default.
- `NEX_CX_PRIVATE_VECTOR_STORAGE_ROOT` overrides the local reference adapter
  root. The capability port remains replaceable by pgvector or an external
  vector database later.
- Chunk and summary vectors are owner scoped, immutable by content id, hash and
  dimension verified on every reload, and stored with private permissions.
- Canonical vector SHA-256 matches the existing public embedding metadata
  contract: compact `{"embedding":[...]}` JSON.
- `persist_and_link_private_vector` writes through the abstract port and adds
  only `embedding_sha256`, `vector_dimension`, and `embedding_storage_uri` to
  public metadata.
- Metadata conflicts fail closed; receipt and linked metadata never contain
  vector values or absolute local paths.

This slice uses deterministic vectors only. It does not call DGX Spark and does
not change a database table or migration. Owner-lineage runtime wiring follows
in Slice 0917.

## Verification

```text
private vector smoke: PASS (10/10 checks)
focused private storage tests: 102 passed; statement 100%; branch 100%
affected embedding/ingestion/repository regression: 275 passed
aggregate regression: 6473 passed
aggregate statement coverage: 76944/77825 (98.8679730163829%)
aggregate branch coverage: 17814/18464 (96.47963604852686%)
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI documents
```
