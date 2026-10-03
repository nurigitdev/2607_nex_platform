# Slice 1290: S129 OA federated PostgreSQL and TLS loopback smoke

## Outcome

- Added an opt-in smoke runner locked to `nex_oa_user@nex_oa_test`.
- Applies the current OA migration inventory and proves that
  `1284_oa_federated_identity` is present in the actual migration ledger.
- Uses a local HTTPS OIDC discovery/JWKS server with a short-lived trusted test
  certificate, an RS256 ID token, the protected OA login route, and the real
  SQLAlchemy repositories.
- Proves provider, digest-only identity, membership, and session persistence,
  then repeats repository/session reads after reconstructing the adapters.
- Deletes all smoke-owned rows and requires zero provider, identity,
  membership, session, subject, and tenant residue.
- Evidence excludes the database URL, ID token, raw external subject, session
  identifier, signing private key, and TLS private key.

## Protected execution

```bash
NEX_OA_FEDERATED_POSTGRES_LOOPBACK_SMOKE=1 \
  ./.venv/bin/python \
  scripts/smoke/run_oa_federated_postgres_loopback_smoke.py --summary
```

The runner reads `NEX_OA_TEST_DATABASE_URL` from `.env.local` and refuses any
database or role other than the dedicated OA test target.
