# Slice 1231: S123 OA credential and session security closure

## Closure Decision

S123 closes the OA credential and session security baseline. The implementation
now provides Argon2id password storage with legacy verification and adaptive
rehash, atomic timed lockout, random idle-bound sessions, password rotation with
session revocation, privacy-safe authentication events, protected contracts,
and actual PostgreSQL evidence.

The S121 current-state compatibility closure now accepts monotonic security
hardening while preserving its eight-control inventory. Its live re-audit moved
from five gaps and one partial control to eight implemented controls and zero
remaining credential/session security gaps.

Closed behavior:

- Argon2id is the default password hash; valid legacy PBKDF2 credentials are
  upgraded after successful verification;
- five failed attempts atomically lock a credential for 900 seconds while
  returning an enumeration-safe error;
- session handles contain 32 bytes of entropy and enforce 1800-second sliding
  idle expiry within the absolute expiry;
- password reset and change atomically revoke matching active sessions;
- credential security writes and event reads require dedicated service scopes;
- auth-event projections exclude passwords, hashes, tokens, and session ids;
- the persistence table remains the short `oa_auth_events` identifier.

Explicitly deferred to focused follow-up requirements:

- multi-factor authentication;
- self-service password reset delivery;
- OIDC/SAML external identity integration;
- signed service tokens and JWKS verification.

## PostgreSQL Evidence

The protected Slice 1230 execution used `nex_oa_test` / `nex_oa_user`, applied
`1225_oa_credential_session_security`, persisted auth events: `12` total,
revoked sessions: `2`, confirmed Argon2id rehash and timed lock recovery, and
left cleanup residue across all six tables: `0`. No DGX or remote model provider
was required.

## Quality Cadence

- Slice Gate: Slices 1222-1230
- Checkpoint Gate: Slice 1226
- Full Gate: Slice 1231

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_s123_oa_credential_session_security_closure.py \
  --summary

./scripts/quality/run_quality_gate.sh
```

Observed evidence:

- protected PostgreSQL smoke: `1 passed`, `0 skipped` for the selected test;
- S123 closure: `PASS`, evidence `9/9`, components `5/5`, operations `3`,
  PostgreSQL auth events `12`;
- Python regression: `9992 passed`, `13 skipped`;
- statement coverage: `98.50%`;
- branch coverage: `97.00%`;
- contract validation: schemas `134`, examples `192`, negative examples `162`,
  OpenAPI documents `7`;
- AE Web regression: `293 passed`, `0 failed`, `0 skipped`;
- Full Gate exit status: `0`.
