# Slice 1223: OA Argon2id adaptive rehash

## Result

- Added `argon2-cffi` as an explicit runtime dependency and made Argon2id the
  default for newly created local credentials.
- Retained PBKDF2-SHA256 parsing and constant-time verification for existing
  records.
- Successful PBKDF2 authentication upgrades the stored hash to current
  Argon2id parameters. Failed authentication never changes stored material.
- Adaptive rehash updates `updated_at` but preserves `password_changed_at`, so
  operational hash upgrades are not represented as user password changes.
- Public snapshots and evidence still exclude passwords and hash material.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_argon2_adaptive_rehash.py \
  --coverage-target services/nex-oa/nex_oa/credentials.py \
  --coverage-target scripts/smoke/run_oa_argon2_adaptive_rehash.py \
  --smoke scripts/smoke/run_oa_argon2_adaptive_rehash.py
```

