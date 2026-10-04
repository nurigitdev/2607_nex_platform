# Slice 1339: Platform OA-backed trust PostgreSQL smoke

## Outcome

- Added an opt-in protected runner that migrates the actual OA, AE, CX, MO,
  and AG test databases and starts the five API processes over loopback HTTP.
- Seeded one temporary OA user, four least-privilege service principals, and
  one 3072-bit RSA signing key held by the test-only file custody adapter.
- Proved actual credential login, opaque AE browser session restoration,
  audience-bound service-token exchange, JWKS verification, sensitive-route
  introspection, and request/trace propagation through OA, AE, CX, MO, and AG.
- Proved fail-closed wrong-audience, missing-scope, revoked-session, and
  revoked-service-token behavior across two fresh process generations.
- Propagated correlation identifiers into OA HTTP introspection so security
  audit rows remain attributable and residue-free cleanup is deterministic.
- Removed all seeded rows and temporary key material after success and failure;
  remote embedding, reranking, and generation providers were not contacted.

## Protected Execution

Set `NEX_PLATFORM_OA_BACKED_TRUST_POSTGRES_SMOKE=1` and provide all five
`NEX_*_TEST_DATABASE_URL` values, then run:

```bash
./.venv/bin/python scripts/smoke/run_platform_oa_backed_trust_postgres_smoke.py --summary
```

The protected run reached all 89 migration heads, passed five of five trust
hops and four of four denial scenarios, restored the user session and signing
key after restart, retained service-token revocation, and reported zero cleanup
or temporary-key residue.

## Verification

- 58 focused tests passed, including the actual five-database/two-generation
  loopback HTTP smoke.
- Changed-scope coverage passed at 98.39% statement and 97.53% branch; the
  protected runner retained 97.49% statement and 94.44% branch coverage.
- Contract validation passed for 156 schemas, 214 examples, 184 negative
  examples, and seven OpenAPI documents.
- A direct post-run PostgreSQL inspection confirmed zero S134 tenants,
  principals, keys, correlated auth events, operational events, and revocation
  evidence rows.
