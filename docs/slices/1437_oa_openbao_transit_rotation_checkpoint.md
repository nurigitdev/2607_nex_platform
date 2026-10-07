# Slice 1437: OA OpenBao Transit Rotation Checkpoint

## Outcome

- Added exact-version Transit RSA-3072 rotation with one-step version
  validation and fail-closed mismatch handling.
- Added an atomic repository operation that changes the previous OA key to
  `VERIFY_ONLY` and the prepublished key to `ACTIVE` in one transaction.
- Preserved exactly one active key and the old/new JWKS overlap across service
  reconstruction.
- Proved old-token validation, new-token issuance, token revocation,
  introspection, rollback-before-activation, and public-only evidence.

## Atomicity Decision

Two independent state updates are not acceptable because failure after the
first update could leave OA without an active signing key. In-memory and
SQLAlchemy repositories therefore expose one rotation transaction. A revision,
state, uniqueness, or activation-time failure rolls back both key records.

## Verification

- Focused tests: `47 passed`, covering Transit version conflicts, atomic
  memory/SQLite commit and rollback, service activation, and checkpoint
  evidence branches.
- OA Slice Gate after branch completion: `1031 passed, 11 skipped`;
  statement coverage was 98.49% and branch coverage was 97.91%.
- Checkpoint Gate: `11804 passed, 30 skipped`; repository-wide statement
  coverage was 98.94% and branch coverage was 97.41%.
- The Transit key adapter, signing-key service, atomic repository branch set,
  and rotation evidence runner each retained 100% branch coverage.
- Contract validation passed with 166 schemas, 228 positive examples, 196
  negative examples, and 7 OpenAPI documents.
- Deterministic evidence uses SQLite/in-memory persistence and an OpenBao
  protocol double; live OpenBao and `nex_oa_test` remain mandatory in Slice
  1441 rather than being represented as protected evidence here.
