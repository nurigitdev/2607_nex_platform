# Slice 1428: Platform Production API Key Custody

## Outcome

- Restricted embedding, reranking, and generation provider API keys to the MO
  process environment.
- Added fail-closed admission for missing MO keys and any provider-key presence
  in OA, AE, CX, or AG process environments.
- Added recursive redaction for sensitive mapping keys, known runtime values,
  Bearer headers, nested sequences, exception text, and command projections.
- Kept raw API key values and value hashes out of custody evidence.

## Decision

CX and other services continue to call MO service APIs; they must not receive
provider credentials. Redaction is defense in depth and does not make it safe
to persist or intentionally log raw provider requests.

## Verification

The deterministic smoke uses synthetic values only and contacts no database,
network, provider, TLS endpoint, or production system.

- Focused tests: `8 passed`; runtime module and runner statement/branch
  coverage `100%`.
- Platform Slice Gate: `329 passed, 6 skipped`; runner statement/branch
  coverage `100%`.
- Contract validation: `166` schemas, `228` examples, `196` negative examples,
  and `7` OpenAPI documents.
