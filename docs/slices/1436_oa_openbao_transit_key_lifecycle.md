# Slice 1436: OA OpenBao Transit Key Lifecycle

## Outcome

- Added an operator-only Transit provisioner that creates exact RSA-3072 keys
  with derivation, export, and plaintext backup disabled.
- Read the key policy and public PEM back from Transit before accepting a key
  version; malformed, non-signing, exportable, non-RSA, and non-3072 responses
  fail closed.
- Converted only the public RSA key to JWK and bound it to a version-pinned
  `vault://openbao/transit/keys/.../versions/N` reference.
- Registered that projection through the existing production
  `OaSigningKeyService`, which stores the opaque reference but never exposes it
  from its response or JWKS.

## Security Decision

Key provisioning is not an OA application runtime capability. A separate
operator AppRole may create and inspect key metadata, while the OA runtime role
will receive only sign and public-key read permissions. The provisioner has no
private-key export or backup operation and revokes its own short-lived token.

## Verification

- Focused tests: `68 passed`, including key-policy, public-key, AppRole,
  reference, registration, redaction, and closed-provisioner branches.
- Slice Gate: `1016 passed, 11 skipped`; statement coverage was 98.49% and
  branch coverage was 97.87%.
- The Transit provisioner and deterministic lifecycle runner both retained
  100% statement and branch coverage.
- Contract validation passed with 166 schemas, 228 positive examples, 196
  negative examples, and 7 OpenAPI documents.
- The deterministic lifecycle smoke uses a protocol double and does not
  contact OpenBao, PostgreSQL, an IdP, a registry, or production.
