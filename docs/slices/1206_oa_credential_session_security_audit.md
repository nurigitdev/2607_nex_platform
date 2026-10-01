# Slice 1206: OA credential/session security audit

## Goal

Audit the current employee-password credential and opaque user-session security
boundary, then run the fifth-Slice Checkpoint Gate.

## Result

- Credential secrets use random salts, PBKDF2-SHA256, and constant-time digest
  comparison; public snapshots reject or omit raw password/hash/token material.
- User sessions enforce a bounded one-day maximum TTL and support persisted
  introspection and idempotent revocation.
- PBKDF2 remains the compatibility algorithm. Argon2id migration and login-time
  adaptive rehash are not implemented.
- `failed_attempt_count` and `locked_at` exist in the schema, but failed login
  verification does not update them atomically or enforce an attempt threshold.
- Password change/reset/rotation is absent; the operator `ensure` path is
  create-once and idempotent.
- Session ids are deterministic UUID5 values derived from identity and timestamp
  claims, rather than cryptographically random opaque identifiers.
- Login, issue, introspect, and revoke paths do not emit auth-specific safe
  operational events.
- These gaps require targeted S122+ hardening. Slice 1206 changes no credential,
  session, table, or migration behavior.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_oa_credential_session_security_audit.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_credential_session_security_audit.py \
  --coverage-target services/nex-oa/nex_oa/credential_session_security_audit.py \
  --coverage-target scripts/smoke/run_oa_credential_session_security_audit.py \
  --smoke scripts/smoke/run_oa_credential_session_security_audit.py

./scripts/quality/run_checkpoint_gate.sh
```

Observed evidence:

- OA Slice Gate: `116 passed`; statement `97.60%`, branch `95.52%`.
- New audit/runner statement and branch coverage: `100%`.
- Checkpoint Gate: `9,228 passed`, `11 skipped`, `123 warnings` in `580.38s`.
- Checkpoint coverage: statement `98.80%`, branch `97.03%`.
- Contract validation: `130` schemas, `188` examples, `157` negative
  examples, and `7` OpenAPI documents.
