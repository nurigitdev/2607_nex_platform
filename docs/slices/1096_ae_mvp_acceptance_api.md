# Slice 1096: AE MVP Acceptance Protected API

## Goal

Expose the privacy-safe AE service MVP acceptance decision through one
server-selected, read-only operations route.

## Route

`GET /admin/v1/operations/mvp-acceptance`

- A valid `nex-ae-api` service claim or user claim with the `admin` role is
  required. Viewer and unauthenticated requests are rejected.
- The server selects policy, clock, and evidence provider. Posted evidence is
  not accepted and the route has no mutation method.
- Repository-only evidence intentionally yields `BLOCKED` because runtime,
  PostgreSQL, live-provider, browser, runbook, and handoff evidence is absent.
- Evidence-provider exceptions are redacted and converted to `UNAVAILABLE`;
  all gates then block without returning exception details.
- The response includes only normalized gate states, reason codes, acceptance
  ID, trace ID, and safe summary metadata.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ae_mvp_acceptance_api.py \
  --cov=nex_ae_api.mvp_acceptance_api --cov-branch --cov-report=term-missing
```

No table or migration is added.
