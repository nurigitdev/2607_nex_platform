# Slice 1229: OA credential security contract hardening

## Result

- Added strict canonical schemas for credential rotation responses and
  tenant-bounded authentication event lists.
- Registered positive fixtures and negative privacy fixtures that reject
  `password_hash` and `session_id` leakage.
- Documented password change, password reset, and security-event reads in OA
  OpenAPI with service bearer authentication and dedicated read/write scopes.
- Rebased OA contract inventory to 34 runtime operations, 11 documented
  operations, six schemas, and 23 explicitly classified legacy route gaps.
- Confirmed all eight credential/session security controls are implemented.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_credential_security_contracts.py \
  --coverage-target scripts/smoke/run_oa_credential_security_contracts.py \
  --smoke scripts/smoke/run_oa_credential_security_contracts.py
```

Observed result: `294 passed, 1 skipped`; overall statement `98.28%`, overall
branch `96.10%`, contract-runner statement/branch `100%`, contract inventory
`134/192/162`, three protected operations, security controls `8/8`, and
remaining classified drift `23`.
