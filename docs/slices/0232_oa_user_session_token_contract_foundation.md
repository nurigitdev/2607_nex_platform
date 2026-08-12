# Slice 0232: OA User Session/Token Contract Foundation

## Scope

Slice 0232 adds the mock-first user token and browser session contract foundation
needed by authenticated AE Web fetch mode.

Implemented:

- Added `UserClaims`, `IssuedUserToken`, and `UserClaimValidationResult` to
  shared `nex_runtime.auth`.
- Added `issue_mock_user_token()`, `validate_mock_user_token()`, and
  `validate_user_authorization_header()`.
- Kept user-token validation separate from service-token validation so browser
  tokens cannot satisfy service-to-service guards.
- Added `contracts/schemas/service/nex_oa/browser_session.v1.schema.json`.
- Added positive and negative browser session fixtures and registered them in
  contract validation indexes.
- Added regression coverage for user-token issue, header validation,
  wrong-audience, missing-scope, expiry, future-token, malformed-payload, and
  static-claim mismatch branches.

## Boundary

The browser session contract is a safe snapshot, not a raw credential envelope.
It may expose tenant/user refs, roles, scopes, token use, and timestamps. It
must not expose access tokens, passwords, service tokens, provider secrets, or
database details.

The mock user token is for local/test authenticated runtime wiring only. The
real OA implementation can replace its issuer later while preserving the same
claim boundary.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_auth.py tests/test_contract_validation.py -q
```

Contract validation:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
46 passed in 1.62s
```

Observed contract validation:

```text
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
```

Observed full quality gate:

```text
1682 passed, 1 warning in 55.36s
statement_coverage=98.04% threshold=95.00%
branch_coverage=93.91% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
