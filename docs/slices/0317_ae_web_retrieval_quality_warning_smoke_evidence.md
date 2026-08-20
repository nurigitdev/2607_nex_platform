# Slice 0317: AE Web Retrieval-Quality Warning Smoke Evidence

## Scope

Add a default smoke evidence runner for the AE Web retrieval-quality warning
surface introduced in Slice 0316.

This slice does not change database schema, provider configuration, or
PostgreSQL smoke behavior. It validates static browser/runtime wiring only, so
no test DB connection is required for this slice.

## Implemented

- Added `scripts/smoke/run_ae_web_retrieval_quality_warning_smoke.py`.
- Validated dev-server HTML anchors for:
  - `retrieval-quality-warnings`;
  - `retrieval-feedback`;
  - `retrieval-client-summary`;
  - `retrieval-scope-preview`;
  - `message-list`.
- Validated production source anchors for the warning adapter, retrieval client,
  main renderer, and CSS.
- Added raw-detail leak checks for prompt text, source text, provider endpoint,
  database endpoint, storage path, and secret fragments.
- Wired the smoke runner into the default quality gate.

## Runtime Behavior

The runner starts the AE Web dev server by default and fetches the browser HTML
before checking source files on disk. It emits a compact summary:

```text
ae_web_retrieval_quality_warning_smoke=pass slice=Slice_0317 ...
```

Failures identify the first failing evidence group as `missing_html`,
`missing_source`, `forbidden`, or `error`.

## Evidence

- Targeted smoke tests:
  `./.venv/bin/pytest tests/test_ae_web_retrieval_quality_warning_smoke.py -q`
- Targeted runner:
  `./.venv/bin/python scripts/smoke/run_ae_web_retrieval_quality_warning_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
