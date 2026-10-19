# P7-CA02: Work Delegation Authorization and Final Contract Closure

## Status

Completed on 2026-10-19. P7 Final Freeze is restored and P8 entry remains
authorized.

## Changes

- Added a shared WC authorization helper and typed OA subject-denial exception.
- Added fresh `work:delegate` authorization before every WorkItem create or
  idempotent replay.
- Kept subject denial and malformed authorization as non-retryable `403`, while
  network, service-trust, and dependency failures remain retryable `503`.
- Bound replay to the original `requester.entity_id`; another authorized
  requester receives `409 wc.work_item_idempotency_conflict` with zero mutation.
- Added nullable, historical-row-safe authorization evidence columns through
  `1003_wc_work_item_authorization`.
- Reused the same helper for Claim and WorkResult authorization parsing.
- Aligned WC OpenAPI with the runtime WorkResult route and authorization status
  matrix.
- Explicitly deferred the detailed P7-FR-101 WC operations projection into AG.

## Actual Acceptance

- Negative OA/WC/AE PostgreSQL smoke: 23/23 checks, one `work:delegate` read,
  zero WorkItem/Claim/Assignment/handoff/child execution mutation, zero residue.
- P7-S8 PostgreSQL recovery smoke: 26/26 checks, zero residue.
- P7-S9 Golden B: 51/51 checks against actual AE/WC/OA test databases, live
  Qwen3.5-4B generation, and admitted NSL revision
  `3b4cb198888570a857e6fb0d3aa077930bb23504`.
- Golden B OA gates: one each for `work:delegate`, `work:claim`, and
  `work:result:submit`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  8 OpenAPI documents.
- Repository Full Gate: 15,407 passed, 48 protected skips; statement 96.83%,
  branch 96.22%.

Protected evidence contains no credentials, endpoint values, raw prompts,
provider output, hidden reasoning, or private result content.
