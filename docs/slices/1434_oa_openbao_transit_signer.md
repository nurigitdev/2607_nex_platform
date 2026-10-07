# Slice 1434: OA OpenBao Transit Signer

## Outcome

- Added an OA-local OpenBao Transit signing adapter without expanding the
  existing JWT composition protocol.
- Restricted custody references to an exact `vault://openbao/transit/keys/...`
  versioned form with no credentials, port, query, or fragment.
- Fixed RSA-3072 RS256 request semantics to SHA-256 plus PKCS#1 v1.5 and
  validated the returned key version and 384-byte signature.
- Added AppRole authentication, bounded input, redacted transport failures,
  token self-revocation, and fail-closed post-close behavior.

## Security Decision

The adapter exposes signing only. It has no key creation, export, decrypt,
admin, policy, or root-token operation. Slice 1435 owns explicit runtime
selection and TLS/AppRole file configuration; production still defaults to the
unavailable signer until that wiring is complete.

## Verification

- Focused tests: `46 passed`, including real RSA-3072 verification and all
  reference, response, authentication, transport, and close failure branches.
- Slice Gate: `995 passed, 11 skipped`; statement coverage was 98.47% and
  branch coverage was 97.83%.
- The Transit adapter and evidence runner retained 100% statement and branch
  coverage.
- Contract validation passed with 166 schemas, 228 positive examples, 196
  negative examples, and 7 OpenAPI documents.
- No OpenBao, PostgreSQL, IdP, registry, or production resource is contacted.
