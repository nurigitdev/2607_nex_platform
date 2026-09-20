# Slice 0895: AG MVP acceptance protected API

## Goal

Expose the S90 decision through a protected, read-only NeX-AG operations route
without allowing callers to submit or forge acceptance evidence.

## Implementation

- Added `GET /admin/v1/operations/mvp-acceptance` for service principals and OA
  admin users.
- The route has no request body and no write counterpart. A posted evidence
  document is rejected with method-not-allowed.
- Evidence comes only from an injected server-side provider. Provider failures
  are redacted and return a fail-closed `BLOCKED` projection.
- The default repository provider proves only the closure inventory. It leaves
  the remaining seven gates blocked until the later S90 evidence pack is run.
- Responses expose normalized gate status, blocker reason codes, request trace,
  and evidence source availability; raw evidence and provider errors stay out.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_mvp_acceptance_api.py \
  --cov=nex_ag.mvp_acceptance_api --cov-branch \
  --cov-report=term-missing
```

Observed verification:

```text
focused API tests: 7 passed, 1 known warning
API module statement/branch coverage: 100%
aggregate regression: 6216 passed, 1 known warning
statement=75114/75995=98.840713204816%
branch=17572/18222=96.432883327845%
```
