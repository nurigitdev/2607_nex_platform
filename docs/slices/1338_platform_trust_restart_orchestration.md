# Slice 1338: Platform trust restart orchestration

## Outcome

- Attached OA's own signed route admission to the durable signing-key and
  token-validation services without recursive HTTP calls back into OA.
- Kept AE, CX, MO, and AG on the existing OA HTTP JWKS/introspection clients;
  only the authority itself uses the local adapters.
- Extracted late-bound service-token routes so OA can attach them after its
  persistence-backed trust services are constructed.
- Froze a two-generation, sixteen-phase trust restart plan with OA-first
  startup, reverse shutdown, session/JWKS restoration, durable revocation,
  cleanup, and explicit exclusion of remote model providers.

## Verification

- Regression signs and verifies a real RS256 token through the OA-local JWKS
  source and requires local validation-service introspection on the sensitive
  route.
- Regression covers mock/signed/dual profile behavior, late route attachment,
  duplicate registration, unavailable runtime, every restart-plan drift axis,
  and exact restart checkpoint inventory.
- This Slice defines executable orchestration and does not claim process or
  PostgreSQL evidence; that protected execution is Slice 1339.
- The Slice Gate passed with 999 tests, eleven protected PostgreSQL skips,
  98.45% statement coverage, and 97.77% branch coverage. The new restart-plan
  module retained 100% statement and branch coverage.
