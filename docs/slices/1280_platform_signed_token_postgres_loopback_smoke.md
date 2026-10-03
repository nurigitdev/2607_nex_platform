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

## Observed evidence

- Actual database/role: `nex_oa_test` / `nex_oa_user`
- Migrations: `16/16`
- Consumers: `4/4`
- Issued RS256 tokens: `4`
- Mock-token rejection: `4/4`
- Cleanup residue: `0`
- Slice Gate: `811 passed, 6 skipped`
- Statement coverage: `99.09%`
- Branch coverage: `98.18%`
- Target statement/branch coverage: `100%` / `100%`

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
