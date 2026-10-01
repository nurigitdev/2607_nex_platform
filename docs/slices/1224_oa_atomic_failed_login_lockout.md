# Slice 1224: OA atomic failed-login lockout

## Result

- Five failed password verifications lock a local credential for 900 seconds.
- PostgreSQL verification locks the credential row and commits failure state
  before returning the generic authentication error. The counter increment is
  atomic and cannot be lost by the verification exception rollback.
- Missing, wrong-password, and locked credentials return the same
  `oa.credential_not_verified` response to avoid account-state disclosure.
- A correct password after lock expiry restores `ACTIVE`, clears the counter,
  and clears `locked_at`. A success before expiry remains rejected.
- Memory and SQLAlchemy adapters share the same state transition helpers.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_atomic_login_lockout.py \
  --coverage-target services/nex-oa/nex_oa/credentials.py \
  --coverage-target scripts/smoke/run_oa_atomic_login_lockout.py \
  --smoke scripts/smoke/run_oa_atomic_login_lockout.py
```

