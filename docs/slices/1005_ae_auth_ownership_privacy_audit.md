# Slice 1005: AE authentication, ownership, and privacy audit

## Goal

Re-audit which AE routes derive owner scope from authenticated browser claims
and which legacy routes still depend on service claims plus payload identifiers.

## Decision

- Session redaction, the shared facade auth context, upload, document-library,
  retrieval, Web route guard, and CX owner-header propagation are hardened.
- Workspace, chat, and artifact-file preview/download routes still use a
  service-claim-only helper. Browser claim ownership is therefore not enforced
  at those route boundaries.
- Those three surfaces are high-risk refactor candidates and must be addressed
  before expanding browser-facing AE features.
- Browser owner authority remains the validated OA user claim. Service calls
  require a validated service claim plus explicit owner scope.
- Unauthorized and not-found behavior must remain indistinguishable, and raw
  credentials or tokens must never enter API output or diagnostics.
- Slice 1005 changes no runtime behavior and adds no table.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_ae_auth_ownership_privacy_audit.py --summary
./.venv/bin/pytest -q tests/test_ae_auth_ownership_privacy_audit.py \
  --cov=nex_ae_api.ownership_privacy_audit \
  --cov=run_ae_auth_ownership_privacy_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

- Focused tests: `6 passed`; the audit module and runner both reached `100%`
  statement and branch coverage.
- Slice Gate: `1,876 passed`; statement coverage `97.73%`; branch coverage
  `95.41%`.
- Contract validation: `92` schemas, `145` examples, `109` negative examples,
  and `7` OpenAPI documents passed.
- Audit evidence: `10` surfaces inspected, `7` hardened, `3` refactor
  candidates, `3` high-risk findings, and `0` audit execution issues.
