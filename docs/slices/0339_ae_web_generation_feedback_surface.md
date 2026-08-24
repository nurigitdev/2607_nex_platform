# Slice 0339: AE Web Generation Feedback Surface

## Scope

Expose a browser-safe AE Web surface for users to submit generation feedback
against an assistant response and route it to the AE feedback facade.

## Implemented

- Added `generationFeedback.js` with:
  - safe request builder for `/api/v1/chat/interactions/{interaction_id}/feedback`;
  - mock and fetch clients;
  - normalized submission result;
  - browser surface state and summary;
  - sensitive-key guard for raw prompt/output/source and credential material.
- Added `generationFeedbackClient` to the AE Web client registry for mock and
  fetch modes.
- Rendered compact feedback actions on assistant messages:
  - positive;
  - negative;
  - neutral.
- Wired feedback submit state into the browser UI without rendering raw comments,
  prompts, generation output, service tokens, provider endpoints, or database
  endpoints.
- Added node regression coverage for the client, route, fetch behavior, error
  handling, and surface summary.
- Extended static Python checks for the new Web surface and client wiring.

## Evidence

AE Web node regression:

```text
npm test
tests=115 suites=28 pass=115 fail=0
```

Python static regression:

```text
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
15 passed in 0.06s
```

Static browser smoke:

```text
./.venv/bin/python scripts/smoke/run_ae_web_static_browser_smoke.py --summary
ae_web_static_browser_smoke=pass slice=Slice_0227 anchors=17 url=http://127.0.0.1:5227/
```
