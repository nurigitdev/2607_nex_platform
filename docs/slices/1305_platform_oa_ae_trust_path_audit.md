# Slice 1305: Platform OA-to-AE trust propagation audit

## Outcome

- Confirmed OA owns credential login plus session issue, introspection, and
  revocation through four internal HTTP routes.
- Confirmed AE API owns the browser-facing current/login/logout session facade
  and delegates OA-mode operations through `HttpOaUserSessionClient`.
- Confirmed AE authenticates itself to OA with an audience-bound service token
  and propagates request and trace identifiers.
- Confirmed AE Web uses same-origin credentials in fetch mode and does not
  store raw user tokens, service tokens, or passwords in its runtime summary.
- Confirmed user ownership comes from validated OA session claims rather than
  browser request fields.
- Identified the activation gap: repository defaults remain AE `mock` session
  mode and `TEST_MOCK` service-token rollout, while `.env.example` does not
  materialize the OA-mode/SIGNED_ONLY combination as a complete profile.
- Identified `secure=False` as an intentional local HTTP cookie setting that
  must become profile-aware before protected browser acceptance.

## Decision

OA remains the identity authority and AE remains the browser cookie owner. The
existing HTTP boundary is reusable and requires no structural rewrite in S131.
S132 must make activation explicit; S134 must prove the actual OA-backed,
SIGNED_ONLY, revocation-aware browser trust chain and production cookie policy.

No database or remote provider is required for this repository audit Slice.

## Verification

- Focused tests: `4 passed`.
- Slice Gate (`nex-ae-api`): `2,790 passed`, `5 skipped` protected smokes.
- Coverage: statement `98.36%`, branch `96.22%`.
- Changed audit runner coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Audit summary: `4` OA internal routes and `3` AE facade routes are present;
  default activation remains `mock`/`TEST_MOCK`, and the integrated OA profile
  is not yet materialized in `.env.example`.
