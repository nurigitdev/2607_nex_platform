# P8-S18 Voucher Draft Command Contract

## Outcome

The canonical `FINANCE.CREATE_VOUCHER_DRAFT` v1 request and result are now
machine-readable JSON Schemas and are exposed by the NeX-EOS OpenAPI contract.
The request binds BusinessOperation/idempotency/PayloadHash, stable Project and
Account refs, decimal-safe signed amounts, NSL approval lineage, trace lineage,
and optional opaque attachment refs. The result distinguishes created/replayed
idempotency outcomes and committed/not-committed/unknown commit states.

Binary floating-point money, zero lines, wrong stable-reference types, missing
approval lineage, and credential-bearing attachment fields fail contract
validation. Arithmetic balance remains an EOS semantic invariant enforced by
the P8-S19 command service rather than JSON Schema.

## Verification

- positive request/result examples and registered negative examples
- canonical schema index and OpenAPI binding tests
- repository-wide contract validator with `jsonschema` and
  `openapi-spec-validator`
- focused contract regression: 6 passed
- EOS Slice Gate: 243 passed; statement coverage 99%, branch coverage 100%
- contract validation: 176 schemas, 238 examples, 207 negative examples, and
  9 OpenAPI documents
