# Slice 0233: AE API Browser-User Auth Guard Foundation

## Scope

Slice 0233 adds a reusable AE API browser-user auth guard before live AE Web
fetch-mode routes are switched from mock/service-auth testing into user-session
mode.

Implemented:

- Added `services/nex-ae-api/nex_ae_api/auth_guard.py`.
- Added `tests/test_nex_ae_auth_guard.py`.
- The guard validates `token_use=user` tokens with audience `nex-ae-api`.
- Service tokens cannot satisfy browser-user route guards.
- Owner scope is derived from user claims and browser payload owner mismatches
  are rejected.
- Added README and working-doc slice index notes.

## Boundary

This Slice is a foundation, not a route-wide behavior flip. Existing AE facade
routes still keep their current mock/service-auth regression shape until the
next slices wire the guard into specific browser-facing routes.

The guard defines the rule that later route wiring must follow:

- browser principal is a user claim, not a service claim;
- tenant/user owner scope is claim-authoritative;
- browser payload owner fields may be copied for compatibility but cannot
  override claims;
- the returned auth summary never includes raw tokens.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_auth_guard.py tests/test_nex_runtime_auth.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
34 passed, 1 warning in 1.00s
```

Observed full quality gate:

```text
1688 passed, 1 warning in 55.27s
statement_coverage=98.05% threshold=95.00%
branch_coverage=93.93% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
