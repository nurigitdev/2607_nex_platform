# Slice 1225: OA credential/session security persistence migration

## Result

- Added migration `1225_oa_credential_session_security`.
- The credential hash constraint now accepts current `argon2id.v1` and legacy
  `pbkdf2_sha256.v1` records.
- User sessions gain non-null `last_seen_at` and `idle_expires_at`; existing rows
  are backfilled without extending their absolute expiry.
- Added the privacy-safe `oa_auth_events` table for Slice 1228 event emission.
  It stores event classification and lineage, never passwords, hash material,
  session ids, service tokens, or database URLs.
- The longest declared table/index/constraint identifier remains within the
  PostgreSQL 63-byte limit.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_security_persistence_migration.py \
  --coverage-target scripts/smoke/run_oa_security_persistence_migration.py \
  --smoke scripts/smoke/run_oa_security_persistence_migration.py
```

