# Slice 1261: S126 OA Service Principal Lifecycle Closure

## Closure

S126 closes the NeX-OA service-principal and client-credential lifecycle:

- OA owns durable service principal identity, status, audience allowlists, and
  scope allowlists.
- `oa_service_principals` and `oa_service_creds` are the only S126 tables.
- Credentials are stored as Argon2id hashes, displayed once at issue or
  rotation, limited to two active credentials, and bounded to 90 days.
- Rotation supports at most 24 hours of grace; revocation and expiry fail
  credential verification closed.
- Nine internal operations use distinct read/admin scopes and six canonical
  response contracts reject private hashes and unintended raw secrets.
- Actual `nex_oa_test` evidence covers all 15 migrations, restart-safe reads,
  two hashed credentials, zero plaintext matches, and zero cleanup residue.

## S127 handoff

S126 does not claim signed-token runtime readiness. S127 owns:

1. signing-key and token-revocation lifecycle;
2. client-credential token exchange;
3. JWKS publication and introspection runtime;
4. ordered cross-service signed-only rollout.

Remote model providers are unrelated to this boundary and are not required.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_s126_oa_service_principal_lifecycle_closure.py --summary

NEX_OA_SERVICE_PRINCIPAL_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='<OA test database URL>' \
./scripts/quality/run_quality_gate.sh
```

The Full Gate is the authoritative regression, statement/branch coverage,
contract, closure, and protected PostgreSQL acceptance result for S126.

## Observed Full Gate

- Regression: `10,348 passed, 15 skipped`
- Statement coverage: `98.48%`
- Branch coverage: `97.08%`
- Contracts: `147` schemas, `205` positive examples, `175` negative examples,
  and `7` OpenAPI documents
- S126 PostgreSQL smoke: `PASS` against `nex_oa_test`, with all `15`
  migrations applied, `2` client credentials persisted, `2` Argon2id hashes,
  no plaintext credential match, and no cleanup residue
- S126 closure: `PASS`, with `9/9` evidence items, `5/5` components, and `9`
  operations; signed-token runtime remains explicitly deferred to S127
