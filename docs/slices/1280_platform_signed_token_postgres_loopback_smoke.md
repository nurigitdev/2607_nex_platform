# Slice 1280: Platform signed-token PostgreSQL loopback smoke

## Goal

Prove that OA-issued RS256 service tokens persisted through the actual
`nex_oa_test` lifecycle are accepted by every platform consumer.

## Protected workflow

- Run the canonical OA migrations against only `nex_oa_test` as
  `nex_oa_user`.
- Persist one temporary OA service principal, Argon2id credential, and public
  signing-key record.
- Issue audience-bound tokens for AE, CX, MO, and AG.
- Exercise each consumer through a local ASGI loopback in `SIGNED_ONLY`, verify
  signed acceptance, mock rejection, JWKS cache state, and admission counters.
- Confirm raw tokens, raw client secret, and private JWK material are absent
  from PostgreSQL and evidence.
- Delete all temporary rows and assert zero residue.

DGX model providers are unrelated and are not required.

## Verification

```bash
NEX_PLATFORM_SIGNED_TOKEN_POSTGRES_SMOKE=1 \
NEX_OA_TEST_DATABASE_URL='<protected nex_oa_test URL>' \
./.venv/bin/pytest -q tests/test_platform_signed_token_postgres_smoke.py
```

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_platform_signed_token_postgres_smoke.py \
  --coverage-target services/nex-oa/nex_oa/platform_signed_token_postgres_smoke.py \
  --smoke scripts/smoke/run_platform_signed_token_postgres_smoke.py
```
