# Slice 1222: OA credential and session security boundary

## Goal

Start S123 by freezing password, lockout, session, rotation, evidence, and
deferred trust boundaries before changing credential or session behavior.

## Decision

- New password hashes use `argon2id.v1`; existing `pbkdf2_sha256.v1` records
  remain readable and are upgraded after a successful login.
- Five consecutive failures lock a credential for 900 seconds. PostgreSQL
  verification serializes the credential row so concurrent failures cannot
  lose increments or bypass the threshold. Failure responses remain account
  enumeration safe.
- Session ids use `secrets.token_urlsafe`. The default absolute TTL remains
  3600 seconds, the maximum remains 86400 seconds, and idle expiry is 1800
  seconds.
- Password change and reset revoke matching active sessions. Reactivation or
  rotation never restores a revoked session.
- Security mutations require `credential:security:write` and emit safe events
  without passwords, hashes, session ids, database URLs, or service tokens.
- Actual `nex_oa_test` evidence is mandatory. DGX and remote model providers are
  outside this requirement.
- Signed service tokens and JWKS are a separate OA trust requirement rather
  than part of user credential/session hardening.

## Slice Plan

Slices 1222 through 1231 cover boundary, Argon2id compatibility, atomic
lockout, persistence, secure sessions, credential rotation, safe auth events,
contracts/privacy, PostgreSQL evidence, and closure. Slice Gate runs per Slice,
Checkpoint Gate at 1226, and Full Gate at 1231.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_credential_session_security_boundary.py \
  --coverage-target scripts/smoke/run_oa_credential_session_security_boundary.py \
  --smoke scripts/smoke/run_oa_credential_session_security_boundary.py
```

