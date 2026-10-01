# Slice 1228: OA authentication security event persistence

## Result

- Activated the existing short `oa_auth_events` table through memory and
  SQLAlchemy repositories.
- Login, password change/reset, session issue, introspection, and revocation
  routes now emit outcome events without passwords, tokens, or session IDs.
- Event details use a small scalar allowlist; arbitrary metadata is rejected.
- Added a tenant-bounded event read API protected by both `service:access` and
  `credential:security:read`.
- Event persistence failures retain the original authentication outcome and
  emit a fixed privacy-safe error log without exception detail.
- The S121 security audit is now reclassified from `7/1` to `8/0` implemented
  controls.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_auth_events.py \
  --test tests/test_oa_auth_event_flow_runner.py \
  --coverage-target services/nex-oa/nex_oa/auth_events.py \
  --coverage-target scripts/smoke/run_oa_auth_event_flow.py \
  --smoke scripts/smoke/run_oa_auth_event_flow.py
```

Observed result: `288 passed, 1 skipped`; overall statement `98.24%`, overall
branch `96.04%`, auth-event statement/branch `100%`, and smoke checks `7/7`.
