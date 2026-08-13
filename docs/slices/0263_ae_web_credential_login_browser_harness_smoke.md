# Slice 0263: AE Web Credential-Login Browser Harness Smoke

## Scope

Add a deterministic smoke runner that executes the Slice 0261 AE Web
credential-login browser harness and consumes the Slice 0262 protected boundary.
The runner should pass in the default quality gate without live network or
PostgreSQL access, while preserving a clear path for later protected browser
execution.

## Implemented

- Added `apps/nex-ae-web/scripts/runCredentialLoginBrowserHarnessSmoke.mjs`.
- The Node runner emits `ae_web_credential_login_browser_harness_smoke.v1`
  evidence from the fake-fetch credential-login harness:
  - current session read is anonymous
  - credential login returns authenticated session state
  - authenticated runtime composes fetch clients
  - route guard reports `allowed`
  - logout returns anonymous state
  - fetch call sequence is current/login/logout with same-origin credentials
- Added `scripts/smoke/run_ae_web_credential_login_browser_harness_smoke.py`.
- The Python wrapper validates the Slice 0262 boundary, executes the Node smoke,
  redacts protected env values, and emits a quality-gate summary.
- Added `npm --prefix apps/nex-ae-web run smoke:credential-login-harness`.
- Added regression coverage for Node evidence, Python wrapper pass/fail paths,
  timeout/unavailable Node handling, redaction, output writing, CLI summary, and
  docs/quality wiring.
- Added the runner to the default quality gate.

## Evidence

- Local Node smoke:
  `npm --prefix apps/nex-ae-web run smoke:credential-login-harness`
  - Result:
    `ae_web_credential_login_browser_harness_smoke=pass mode=deterministic_fake_fetch route_guard=allowed fetch_calls=3`
- AE Web Node regression:
  `npm --prefix apps/nex-ae-web test`
  - Result: `79 passed`
- Python wrapper regression:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_harness_smoke.py -q`
  - Result: `11 passed`
- Python wrapper coverage:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_harness_smoke.py --cov=run_ae_web_credential_login_browser_harness_smoke --cov-branch --cov-report=term-missing -q`
  - Result: `11 passed`; 100% statement and branch coverage for the new wrapper.
- Boundary and harness smoke regression:
  `./.venv/bin/pytest tests/test_ae_web_credential_login_browser_boundary.py tests/test_ae_web_credential_login_browser_harness_smoke.py -q`
  - Result: `21 passed`
- AE Web static regression:
  `./.venv/bin/pytest tests/test_nex_ae_web_static.py -q`
  - Result: `12 passed`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
  - Result: `1847 passed, 1 warning`
  - Coverage: statement `98.25%`, branch `94.60%`
  - Contract validation: `pass`; schemas `49`, examples `78`,
    negative examples `54`, OpenAPI `7`
  - Default quality smoke summary includes:
    `ae_web_credential_login_browser_harness_smoke=pass boundary=skipped route_guard=allowed fetch_calls=3`

## Next

After Slice 0263, the next natural step is a protected live browser execution
runner that starts AE Web and AE/OA services, points at `nex_ae_test` and
`nex_oa_test`, and proves real credential-login readback through browser-level
automation.
