# Slice 1009: AE Web runtime, i18n, and accessibility drift audit

## Goal

Re-audit AE Web composition, localization readiness, accessibility automation,
and deterministic browser harness coverage before S101 closure.

## Decision

- Keep the semantic HTML baseline, six deterministic Playwright harnesses, and
  the broad module-level Node regression suite.
- Split the 3,220-line `main.js` composition by capability before adding a new
  browser-facing feature.
- Introduce locale catalogs with Korean as the default locale; the current UI
  has hard-coded Korean text and no i18n layer.
- Expand accessibility automation from artifact delivery to the complete
  authenticated workspace and add a standard browser accessibility engine.
- Replace the stale `0.0.0-slice0227` package version during S102 hardening.
- Slice 1009 changes no browser behavior. Actual Playwright evidence remains
  mandatory in Slice 1010.

## Verification

```bash
npm --prefix apps/nex-ae-web test
./.venv/bin/python scripts/smoke/run_ae_web_runtime_audit.py --summary
./.venv/bin/pytest -q tests/test_ae_web_runtime_audit.py \
  --cov=nex_ae_api.web_runtime_audit \
  --cov=run_ae_web_runtime_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

- Node regression: `239 passed`, `0 failed`, `0 skipped` across `54` suites.
- Audit: PASS with readiness `GAPS_CONFIRMED`; source files `42`, test files
  `54`, Playwright scripts/tests `6/6`, and audit issues `0`.
- Drift: `main.js` `3,220` lines, localization files `0`, hard-coded Korean
  lines `135`, accessibility scripts `1`, and required refactors `4`.
- Focused Python tests: `4 passed`; the audit module and runner both reached
  `100%` statement and branch coverage.
- Slice Gate: `1,895 passed`; statement coverage `97.77%`; branch coverage
  `95.47%`.
- Contract validation: `92` schemas, `145` examples, `109` negative examples,
  and `7` OpenAPI documents passed.
