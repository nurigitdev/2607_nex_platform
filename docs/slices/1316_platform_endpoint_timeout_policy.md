# Slice 1316: Platform endpoint and timeout policy

## Outcome

- Centralized five service endpoint names, defaults, normalization, and safe
  URL validation.
- Replaced CX-to-MO five-second defaults with capability budgets that cover MO
  upstream timeout, maximum attempts, Retry-After delay, and a safety margin.
- Set default embedding/reranking/generation client budgets to `60`, `60`, and
  `130` seconds and fail closed when an override is shorter than its computed
  minimum.
- Added capability-neutral `embedding-default` and `reranker-default` aliases
  while preserving the existing mock-named routes for compatibility.
- Wired all three default CX clients to the shared endpoint and timeout policy.
- Updated the S131 CX-to-MO audit to evaluate the shared retry-aware policy
  while retaining the historical S131 gap as immutable document evidence.
- Kept the MO provider registry within its 150-line structure budget by
  extracting canonical alias compatibility data into a focused module.

## Verification

- Focused regression: `40 passed`.
- Slice Gate (`nex-cx`): `2,360 passed`; statement `99.08%`, branch `98.16%`.
- All six changed coverage scopes: statement `100.00%`, branch `100.00%`.
- Fifth-Slice Checkpoint Gate: `10,368 passed`, `24 skipped`; statement
  `98.89%`, branch `97.21%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Smoke summary: five endpoints, safe `60/60/130` second capability budgets,
  two canonical compatibility aliases, and `next=1317`.

The skipped checkpoint tests are protected PostgreSQL/live-provider evidence
owned by later requirements. This Slice performs no provider request or
database mutation.
