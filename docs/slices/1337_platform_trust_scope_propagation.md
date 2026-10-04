# Slice 1337: Platform trust scope propagation

## Outcome

- Froze eight least-privilege grants for AE-to-OA/CX/AG, CX-to-MO, and each
  consumer's separate OA introspection identity.
- Added a side-effect-free internal active-claim boundary that always uses the
  sensitive `CREDENTIAL` route class. It therefore requires both local JWKS
  verification and OA introspection before returning a privacy-safe claim.
- Made wrong-audience and missing-`service:call` requests fail before remote
  introspection and kept raw tokens out of the policy projection.
- Preserved separate service-principal ownership; no browser session or user
  credential is propagated beyond AE.

## Verification

- Signed admission regression covers OA, CX, MO, and AG with the intended
  caller identity for each hop.
- Negative regression covers wrong audience, missing scope, and unavailable
  introspection without contacting PostgreSQL or remote model providers.
- The policy smoke freezes eight grants across four callers and four
  audiences; actual OA HTTP introspection is assigned to Slice 1339.
- The Slice Gate passed with 698 tests, one protected PostgreSQL skip, 98.48%
  statement coverage, and 97.13% branch coverage.
