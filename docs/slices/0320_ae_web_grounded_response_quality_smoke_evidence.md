# Slice 0320: AE Web Grounded Response Quality Smoke Evidence

## Scope

Add default smoke evidence for the AE Web grounded response citation-quality
surface introduced in Slice 0319.

This slice does not change database schema, provider configuration, or
PostgreSQL smoke behavior. It validates static browser/runtime wiring only, so
no test DB connection is required for this slice.

## Implemented

- Added `scripts/smoke/run_ae_web_grounded_response_quality_smoke.py`.
- Validated dev-server HTML anchors for:
  - `grounded-response-quality`;
  - `message-list`;
  - `chat-status`;
  - `chat-title`;
  - `retrieval-quality-warnings`.
- Validated production source anchors for the grounded response quality adapter,
  main renderer, and CSS.
- Added raw-detail leak checks for prompt text, evidence text, provider
  endpoint, database endpoint, storage path, and secret fragments.
- Wired the smoke runner into the default quality gate.

## Runtime Behavior

The runner starts the AE Web dev server by default and fetches the browser HTML
before checking source files on disk. It emits a compact summary:

```text
ae_web_grounded_response_quality_smoke=pass slice=Slice_0320 ...
```

Failures identify the first failing evidence group as `missing_html`,
`missing_source`, `forbidden`, or `error`.

## Evidence

- Targeted smoke tests:
  `./.venv/bin/pytest tests/test_ae_web_grounded_response_quality_smoke.py -q`
- Targeted runner:
  `./.venv/bin/python scripts/smoke/run_ae_web_grounded_response_quality_smoke.py --summary`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
