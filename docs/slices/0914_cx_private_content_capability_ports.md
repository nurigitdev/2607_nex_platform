# Slice 0914: CX private content storage capability ports

## Goal

Define replaceable owner-scoped ports for private text and vector payloads.

## Implementation

- `CxPrivateTextStore` covers chunk and summary text.
- `CxVectorStore` covers chunk and summary embeddings.
- Every payload key binds tenant, owner subject, payload kind, and content id.
- Access checks collapse cross-owner lookups to not-found semantics.
- Text/vector writes require SHA-256 verification; vectors also require finite
  numeric values and a positive dimension.
- Storage receipts expose only backend, URI, hash, size, dimension, and owner
  metadata. They never include private text or vector values.

This slice defines capability contracts only. The local text adapter follows in
Slice 0915, and vector persistence follows in Slice 0916. No route, database,
migration, or provider behavior changes here.

## Verification

```text
capability contract evidence: PASS (6/6 checks, 2 protocols)
focused tests: 45 passed; statement 100%; branch 100%
aggregate regression: 6416 passed
aggregate statement coverage: 76599/77480 (98.86293236964377%)
aggregate branch coverage: 17764/18414 (96.47007711523841%)
contract validation: 82 schemas, 133 examples, 97 negative examples, 7 OpenAPI documents
```
