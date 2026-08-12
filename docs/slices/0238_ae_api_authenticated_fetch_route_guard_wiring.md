# Slice 0238: AE API Authenticated Fetch Route-Guard Wiring

## Scope

Slice 0238 connects AE Web authenticated fetch-mode to AE API facade routes
without weakening existing service-token behavior.

Implemented:

- Added `nex_ae_api.route_auth` as a shared facade-route auth boundary that
  accepts either service claims or browser user sessions.
- Updated AE upload, document-library, document-detail, and retrieval facade
  routes to accept authenticated browser sessions.
- Kept service-token callers compatible with existing regression behavior.
- Applied claim-authoritative browser owner scope before upload handoff
  forwarding.
- Filtered document list/search results to the authenticated browser owner
  scope.
- Rejected document detail, upload readback, and retrieval readback when the
  stored owner/actor scope does not match the browser claim.
- Added focused regression coverage for service mode, browser Authorization
  headers, browser cookies, owner-scope mismatch, and actor-scope mismatch.

## Boundary

AE API facade routes now support two explicit modes:

- `service`: existing service-to-service token behavior, with payload/stored
  owner scope preserved.
- `browser_user`: AE Web same-origin session behavior, with owner scope derived
  from the authenticated user claim.

Browser user routes never accept client-supplied owner scope as authoritative.
They also never expose raw user tokens, service credentials, passwords,
provider endpoints, database URLs, source bytes, source text, storage keys,
storage URIs, or local filesystem paths.

This Slice is route-guard regression work. PostgreSQL smoke is not required
unless a later Slice performs a protected live fetch-mode scenario against the
test databases.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_route_auth.py tests/test_nex_ae_uploads.py tests/test_nex_ae_documents.py tests/test_nex_ae_retrieval.py -q
```

Observed targeted result:

```text
69 passed, 1 warning in 1.94s
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed full quality gate:

```text
1707 passed, 1 warning in 61.65s
statement_coverage=98.05% threshold=95.00%
branch_coverage=93.97% threshold=85.00%
contract_validation=pass schemas=49 examples=78 negative_examples=54 openapi=7
ae_web_fetch_mode_postgres_smoke=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE
```
