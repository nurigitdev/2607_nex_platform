# Slice 1296: OA signing-key rotation and restart smoke

## Outcome

- Added a protected PostgreSQL smoke locked to
  `nex_oa_user@nex_oa_test`.
- Registers an old and a new RS256 public key while private key material stays
  in the external-custody test adapter.
- Issues a token with the old ACTIVE key, transitions it to `VERIFY_ONLY`, and
  activates the prepublished replacement key.
- Disposes the first OA runtime, reconstructs repositories and services, then
  issues a new token through the replacement key.
- Proves both tokens validate after restart, both public keys overlap in JWKS,
  and exactly one key remains ACTIVE.
- Verifies PostgreSQL contains no private JWK member or raw token and removes
  all smoke-owned rows with zero residue.

The in-memory custody adapter models an external signer that remains available
across an OA service-process restart. Production KMS, Vault, or PKCS#11 wiring
remains a deployment responsibility and is not claimed by this smoke.

## Protected execution

```bash
NEX_OA_KEY_ROTATION_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test' \
./scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_oa_key_rotation_restart_smoke.py \
  --coverage-target scripts/smoke/run_oa_key_rotation_restart_smoke.py \
  --smoke scripts/smoke/run_oa_key_rotation_restart_smoke.py
```

The database URL is supplied only through the local environment.

## Verified evidence

- Actual PostgreSQL target: `nex_oa_user@nex_oa_test`
- Migration inventory: `17`
- Rotation workflow checks: `5`
- Overlapping JWKS keys: `2`
- ACTIVE signing keys: `1`
- Cleanup residue: `0`
- Checkpoint Gate: `10223 passed`, `20 skipped`
- Coverage: statement `98.89%`, branch `97.20%`
- Smoke runner coverage: statement `100.00%`, branch `100.00%`
