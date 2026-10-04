# OA MVP Platform Trust Operations

## Preconditions

- Use only the dedicated `nex_oa_test` database for protected acceptance.
- Supply `NEX_OA_TEST_DATABASE_URL` through the local process environment.
- Keep production and test private signing keys in external custody; PostgreSQL
  stores only a custody reference and public JWK.
- Remote model providers are not required for OA trust acceptance.

## Execution Order

Run the protected evidence in this order:

1. `run_oa_identity_session_authorization_restart_smoke.py`
2. `run_oa_key_rotation_restart_smoke.py`
3. `run_oa_revocation_introspection_restart_smoke.py`
4. `run_oa_cross_service_trust_smoke.py`
5. `run_s130_oa_mvp_platform_trust_acceptance.py`
6. `run_quality_gate.sh`

Every protected command must set its documented opt-in variable to `1` and
must point `NEX_OA_TEST_DATABASE_URL` at `nex_oa_user@nex_oa_test`. Never place
the password, client credential, access token, raw JTI, or private key in the
command output or committed evidence.

## Expected Evidence

- Migration inventory and ledger count are both current.
- Identity, membership, credential, session, role, group, and scope reads work
  after an OA runtime reconstruction.
- Key rotation leaves exactly one ACTIVE key while the previous VERIFY_ONLY
  public key remains in JWKS for the verification overlap.
- Revocation survives another runtime reconstruction and introspection reports
  the target token inactive.
- AE API, CX, MO, and AG accept signed service tokens on sensitive routes and
  reject both mock and revoked tokens.
- Each smoke removes its own rows and reports zero cleanup residue.

## Failure Response

Stop progression immediately when any required evidence is skipped, fails, or
targets a database other than `nex_oa_test`. Preserve the redacted evidence,
request and trace identifiers, and migration status. Do not retry by changing
the rollout profile or bypassing introspection.

## Key Rollback

During a planned rotation failure, keep the previously published key available
for verification and restore signing only through an authorized key-state
transition. Do not delete the prior public key before its verification window
closes. SIGNED_ONLY must remain enabled during rollback; never enable a mock token fallback.
A suspected key compromise requires immediate key revocation,
service-credential rotation, and token revocation rather than normal overlap.

## Revocation Response

For a leaked or misused service credential, disable or revoke the credential,
revoke all known active token identifiers through OA, and verify sensitive
routes return an inactive-introspection denial. PostgreSQL evidence may retain
only token-id digests and bounded reason metadata.

## Privacy Controls

- Persist password and client-secret hashes only.
- Persist token identifiers as SHA-256 digests only.
- Publish public JWK members only; private key material remains external.
- Authentication failure events contain bounded operation and error codes, not
  submitted credentials, authorization headers, access tokens, or raw JTI.
- Evidence and logs use redacted database URLs.

## Deferred Deployment Controls

Production activation still requires KMS, Vault, or PKCS#11 custody,
environment-specific TLS and secret injection, operational alert routing, and
an approved external identity provider registration. These deployment controls
must not be represented as completed by the local test acceptance suite.
