# Slice 0264: AE Web Credential-Login Browser Execution Readiness

## Scope

Add a readiness checker for the protected AE Web credential-login browser
execution path. This slice does not run a live browser or PostgreSQL smoke by
itself. Instead, it verifies that the repository is wired for the next protected
execution slices and records the exact test database requirements.

## Implemented

- Added `scripts/smoke/run_ae_web_credential_login_browser_execution_readiness.py`.
- The readiness evidence uses
  `ae_web_credential_login_browser_execution_readiness.v1`.
- The checker validates:
  - Slice 0262 boundary runner availability
  - Slice 0263 deterministic harness runner availability
  - AE Web credential-login form anchors
  - AE Web package smoke command wiring
  - default quality-gate wiring
  - Node command availability
  - deferred Playwright dependency status
  - protected execution plan for Slice 0265
  - PostgreSQL hardening plan for Slice 0266
- The protected execution plan requires real test DB connections when smoke is
  enabled:
  - `NEX_AE_TEST_DATABASE_URL`
  - `NEX_OA_TEST_DATABASE_URL`
- Added regression coverage for default PASS, boundary FAIL, protected env
  redaction, missing path/anchor/wiring failure, missing Node dependency, output
  writing, CLI summary, and docs/quality wiring.
- Added the readiness checker to the default quality gate.

## Evidence

- Readiness summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_credential_login_browser_execution_readiness.py --summary`
  - Result:
    `ae_web_credential_login_browser_execution_readiness=pass boundary=skipped paths=6/6 anchors=7/7 next=Slice_0265`
- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_execution_readiness.py -q`
  - Result: `8 passed`
- Runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_execution_readiness.py --cov=run_ae_web_credential_login_browser_execution_readiness --cov-branch --cov-report=term-missing -q`
  - Result: `8 passed`; 100% statement and branch coverage for the new runner.
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1855 passed, 1 warning`
  - Coverage: statement `98.26%`, branch `94.61%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_web_credential_login_browser_execution_readiness=pass boundary=skipped paths=6/6 anchors=7/7 next=Slice_0265`

This readiness slice does not open PostgreSQL connections. It records that
enabled smoke execution in Slice 0265 and Slice 0266 must use
`NEX_AE_TEST_DATABASE_URL` and `NEX_OA_TEST_DATABASE_URL`.

## Next

Slice 0265 should add the protected execution runner that actually connects to
`nex_ae_test` and `nex_oa_test` when enabled and proves AE/OA credential-login
readback. Slice 0266 should harden that evidence with explicit PostgreSQL
connection, migration, and cleanup observations.
