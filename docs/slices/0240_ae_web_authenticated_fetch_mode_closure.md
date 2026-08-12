# Slice 0240: AE Web Authenticated Fetch-Mode Closure

## Scope

Slice 0240 closes the S24 authenticated fetch-mode track.

Closed scope:

- AE Web has a browser-safe session client, authenticated runtime composition
  gate, and session bootstrap path.
- AE API exposes session facade routes for current-session, login, and logout.
- AE API upload, document, and retrieval facade routes accept browser user
  sessions while preserving service-token callers.
- Browser owner and actor scope is claim-derived at AE API boundaries.
- Protected PostgreSQL smoke now exercises AE facade calls with browser user
  auth and verifies persisted CX retrieval evidence.
- PASS smoke evidence records only redacted/boolean auth observations.

## Guardrails

The closure adds static regression checks so this track does not silently drift
back to service-token fetch smoke:

- The protected fetch-mode PostgreSQL smoke runner must use
  `issue_mock_user_token` and `_ae_browser_headers` for AE facade calls.
- PASS evidence must include `auth_observations`.
- PASS evidence must assert claim-derived upload owner scope and retrieval actor
  scope.
- Slice 0231 through Slice 0240 must remain discoverable from the working docs
  index.

## Deferred Work

The following remain deliberately outside this closure:

- Real OA-backed login/session issuance beyond the current mock session facade.
- Browser UI controls for login/logout.
- End-to-end browser automation that drives the static AE Web shell through a
  real login interaction.
- Remote provider live smoke for retrieval/generation inside the browser path.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_ae_web_authenticated_fetch_mode_closure.py -q
```

Observed targeted result:

```text
2 passed in 0.05s
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed full quality gate:

```text
1709 passed, 1 warning in 58.69s
statement_coverage=98.05% threshold=95.00%
branch_coverage=93.97% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
