# Slice 1438: OA Enterprise OIDC Registration

## Outcome

- Froze the OpenBao staging OIDC issuer, issuer-relative discovery URL,
  canonical OA callback, and confidential client identifier.
- Restricted federation to authorization code, PKCE S256,
  `client_secret_basic`, the exact `openid` scope, and RS256 ID tokens.
- Added fail-closed discovery validation for endpoint TLS, issuer-origin
  binding, and every required capability.
- Kept the client secret in OpenBao. OA receives an S143 owner-scoped opaque
  reference at its process boundary and persists only public provider metadata.

## Trust Decision

OpenBao is the production-shaped staging IdP adapter, while OA remains the
only NeX session and access-token issuer. OA is also the only service allowed
to validate an upstream enterprise identity token. Exact pre-provisioned
subject mapping remains mandatory; email, employee number, and group claims do
not trigger automatic account linking.

The deterministic runner validates registration and discovery contracts
without contacting OpenBao, PostgreSQL, a corporate IdP, or production. Slices
1440 and 1441 own the real single-host Compose registration and protected
acceptance.

## Verification

- Focused registration, discovery, federation verifier, identity, and login
  tests pass (`97 passed`).
- The OA Slice Gate passes with `1071 passed` and `11 skipped`; repository OA
  statement coverage is 98.50%, branch coverage is 97.93%, and both new files
  retain 100% statement and branch coverage.
- The deterministic evidence runner reports 14/14 checks and contains neither
  the client secret nor its opaque reference.
