# Slice 1293: OA signed-token failure audit hardening

## Outcome

- Added durable `SERVICE_AUTH_FAILED` and `TOKEN_VALIDATION_FAILED` OA auth
  event types without creating a new table.
- Failed client-credential exchange and failed authorization of introspection
  or revocation callers emit `SERVICE_AUTH_FAILED`.
- Inactive introspection targets and rejected revocation targets emit
  `TOKEN_VALIDATION_FAILED`.
- Only bounded `operation` and `error_code` details are persisted. Raw access
  tokens, JTI values, client secrets, and authorization headers are excluded.
- Existing operational events for successful issuance and revocation remain
  unchanged.
- Contract enums and the production OA runtime now expose the hardened event
  vocabulary.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_signed_token_failure_audit.py \
  --coverage-target scripts/smoke/run_oa_signed_token_failure_audit.py \
  --smoke scripts/smoke/run_oa_signed_token_failure_audit.py
```
