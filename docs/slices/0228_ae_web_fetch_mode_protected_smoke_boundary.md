# Slice 0228: AE Web Fetch-Mode Protected Smoke Boundary

## Scope

Slice 0228 defines the protected boundary for the next AE Web fetch-mode smoke.
It does not execute live HTTP or PostgreSQL work. Instead, it makes the future
smoke contract testable so a later execution cannot be mistaken for a real DB
smoke when it only skipped or checked metadata.

Implemented:

- Added `scripts/smoke/run_ae_web_fetch_mode_protected_smoke_boundary.py`.
- The boundary checker records required env keys, AE facade routes, required
  execution phases, and evidence/redaction requirements.
- The default quality gate now runs the checker in skipped mode after the
  static browser smoke.
- Added Python regression coverage for default skipped behavior, enabled
  configuration failures, non-test profile rejection, safe browser config
  acceptance, browser secret-key rejection, evidence writing, redaction guards,
  and CLI error handling.

## Boundary

The checker is intentionally not the real protected smoke. It prepares
Slice 0229 by requiring that future execution:

- explicitly enables `NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE=1`;
- uses the `test` profile only;
- receives AE Web URL, AE API base URL, `NEX_AE_TEST_DATABASE_URL`, and
  `NEX_CX_TEST_DATABASE_URL` from operator/server-side env;
- proves PostgreSQL migration/readiness plus write/readback behavior for the AE
  and CX test databases;
- exercises `/api/v1/documents/{document_id}`, `/api/v1/uploads`, and
  `/api/v1/retrieval/contexts`;
- keeps service credentials, database URLs, provider endpoints, source text,
  and storage paths out of browser runtime config and evidence.

The default quality gate may report skipped for this boundary, but an explicitly
enabled protected execution must either produce real test-DB evidence or fail.

## Evidence

Targeted Python regression:

```bash
./.venv/bin/pytest tests/test_ae_web_fetch_mode_protected_boundary.py -q
```

Boundary summary:

```bash
./.venv/bin/python scripts/smoke/run_ae_web_fetch_mode_protected_smoke_boundary.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
tests/test_ae_web_fetch_mode_protected_boundary.py: 10 passed
ae_web_fetch_mode_protected_boundary=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE boundary=pass phases=9
```

Observed full quality gate:

```text
1648 passed, 1 warning
statement_coverage=98.01% threshold=95.00%
branch_coverage=93.82% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
ae_web_static_browser_smoke=pass slice=Slice_0227 anchors=11 url=http://127.0.0.1:5227/
ae_web_fetch_mode_protected_boundary=skipped reason=NEX_AE_WEB_FETCH_MODE_PROTECTED_SMOKE boundary=pass phases=9
```
