# Slice 1390: AE Web Protected PostgreSQL Acceptance

Status: Completed on 2026-10-06.

## Scope

Execute the protected S139 acceptance with actual Chromium, actual service
processes, and the `nex_oa_test`, `nex_ae_test`, and `nex_cx_test` PostgreSQL
databases. Keep model-provider execution deterministic because S136 and S137
already own protected live-provider acceptance.

## Implementation

- Added one opt-in protected runner that composes five evidence sources:
  thirteen-process topology, OA-backed credential login, authenticated upload,
  grounded generation plus artifact delivery, and the two-viewport Korean
  browser acceptance.
- Reused the S109/S137 generation and artifact journey with the deterministic
  MO mock capability while retaining actual AE/CX PostgreSQL, API/Web
  processes, durable lineage, restart-safe artifact rendering, preview, and
  download.
- Required current migrations and exact test-database identities. The evidence
  projection exposes only bounded state, counts, database names, and safe
  source status.
- Required zero owner-scoped AE/CX fixture residue after the protected journey.
  The runner remains skipped in ordinary regression unless
  `NEX_S139_AE_WEB_PROTECTED_ACCEPTANCE=1` is explicitly set.

## Verification

- Focused regression: `16 passed` across the protected acceptance and updated
  authenticated-upload smoke tests.
- Protected acceptance: `PASS`, sources `5/5`, test databases `3`, actual
  processes `13`, Chromium viewports `2`, and all seven AE/CX residue counters
  equal to zero.
- The protected run exposed and corrected two stale smoke-only seams: missing
  CX owner-scope headers and the missing post-upload progress route.
- Slice Gate: `317 passed`; scoped statement and branch coverage both
  `100.00%`; contract validation passed for `166` schemas, `228` examples,
  `196` negative examples, and `7` OpenAPI documents.

## Decision

Remote embedding, reranker, and generation providers are intentionally not
contacted by this Slice. S140 retains the final browser plus all-live-provider
release-candidate matrix.
