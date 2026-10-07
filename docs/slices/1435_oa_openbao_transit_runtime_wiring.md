# Slice 1435: OA OpenBao Transit Runtime Wiring

## Outcome

- Extracted one shared OpenBao TLS/AppRole client-settings loader for both KV
  secret materialization and Transit signing.
- Added explicit `OPENBAO_TRANSIT` signer selection without changing the
  unavailable default or test-only file provider.
- Limited Transit runtime activation to `staging_live` and `production` and
  required absolute CA, role-ID, and secret-ID files plus a positive timeout.
- Authenticated eagerly so malformed settings or denied AppRole credentials
  prevent OA startup instead of failing after token issuance begins.

## Runtime Decision

There is no automatic fallback. A missing or invalid OpenBao setting, TLS
failure, AppRole denial, or unsupported profile leaves OA unable to issue
signed tokens. Existing KV secret resolution and Transit signing now use the
same connection-input validation while retaining separate runtime objects and
OpenBao policy permissions.

## Verification

- Focused tests: `70 passed`, covering the shared OpenBao client settings,
  explicit provider delegation, production-profile admission, configuration
  redaction, RSA-3072 signing, and the S144 boundary regression.
- Slice Gate: `1000 passed, 11 skipped`; statement coverage was 98.47% and
  branch coverage was 97.83%.
- The runtime evidence runner retained 100% statement and branch coverage;
  the Transit adapter retained 99.05% statement and 100% branch coverage.
- Contract validation passed with 166 schemas, 228 positive examples, 196
  negative examples, and 7 OpenAPI documents.
- No live OpenBao, PostgreSQL, IdP, registry, or production resource is
  contacted.
