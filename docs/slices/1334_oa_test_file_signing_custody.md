# Slice 1334: OA test file signing custody

## Outcome

- Added an explicit `TEST_FILE` RSA signing provider for the protected `test`
  profile while retaining unavailable custody as the default.
- Restricted private-key references to local PEM files beneath one configured
  root, disallowing symlinks, URI authorities, query fragments, broad file
  permissions, oversized material, non-RSA keys, and RSA keys below 3072 bits.
- Kept key generation and key material outside application code and committed
  evidence. Production and every non-test profile fail closed.

## Activation

- `NEX_PROFILE=test`
- `NEX_OA_SIGNING_PROVIDER=TEST_FILE`
- `NEX_OA_SIGNING_KEY_ROOT=<operator-created temporary directory>`

The protected S134 runner owns creation, permission hardening, and deletion of
the temporary PEM file.

