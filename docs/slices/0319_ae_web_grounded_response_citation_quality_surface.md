# Slice 0319: AE Web Grounded Response Citation-Quality Surface

## Scope

Render the AE chat grounded response quality contract in AE Web without exposing
raw output, prompt text, evidence text, provider details, local storage paths, or
credential material.

This slice does not change database schema, provider configuration, or
PostgreSQL smoke behavior. It is a static browser/runtime surface change, so no
test DB connection is required for this slice.

## Implemented

- Added `src/groundedResponseQuality.js` to map
  `ae_chat_grounded_response_quality.v1` into
  `ae_web_grounded_response_quality_surface.v1`.
- Added a chat-level grounded response quality status surface.
- Added assistant message chips for grounded response citation quality.
- Added fallback handling for legacy artifact quality summaries while preserving
  redaction metadata.
- Added Node and Python static tests for mapping, rendering anchors, and leak
  guards.

## Runtime Behavior

Grounded assistant responses now show compact quality state:

```text
action=proceed
boundary=PASS / VALIDATED
issues=0
lineage=true / true
```

Non-grounded responses resolve to `NOT_REQUIRED` and remain hidden. `WARN`,
`FAIL`, or unknown grounded status surfaces stay visible with warning or danger
severity.

## Evidence

- AE Web Node tests:
  `npm test --prefix apps/nex-ae-web`
- Targeted static tests:
  `./.venv/bin/pytest tests/test_nex_ae_web_static.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
