# Slice 0217: AE Web Upload Surface Owner-Scope Alignment

## Scope

Slice 0217 audits and refactors the AE Web upload surface so the browser shell
can represent upload ownership before live upload wiring is added.

Implemented:

- Added `apps/nex-ae-web/src/uploadSurface.js`.
- Added a safe upload draft surface aligned to `ae_upload_handoff.v1` and
  `cx_source_ownership_ref.v1`.
- Added canonical owner scope fields for tenant, owner, and uploaded-by subject.
- Added an AE upload handoff payload preview targeting `/api/v1/uploads`.
- Added an Upload panel to the static shell.
- Added Node built-in tests for ownership ref defaults, payload shape, handoff
  normalization, invalid filename, invalid size, invalid hash, invalid draft,
  and invalid handoff branches.
- Updated static Python regression guards for upload DOM anchors, contract
  strings, responsive styles, package metadata, and redaction-sensitive strings.

## Boundary

The Web upload surface remains mock-first. It may display safe upload metadata:
workspace, filename, content type, size, source hash, tenant, owner,
uploaded-by, ownership refs, and the AE handoff route.

It must not display or embed source content, source bytes, base64 payloads,
service tokens, provider URLs, database URLs, CX storage keys, CX storage URIs,
or local filesystem paths.

Future live upload should attach at the upload surface boundary:

```text
nex-ae-web uploadSurface draft
  -> nex-ae-api POST /api/v1/uploads
  -> nex-cx owner-scoped upload registration
```

## Evidence

Targeted Python static regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_web_static.py -q
```

Targeted Node Web regression:

```bash
npm --prefix apps/nex-ae-web test
```

JavaScript syntax check:

```bash
node --check apps/nex-ae-web/src/main.js
node --check apps/nex-ae-web/src/documentDetailClient.js
node --check apps/nex-ae-web/src/uploadSurface.js
```

Static dev-server smoke:

```bash
PORT=5217 npm --prefix apps/nex-ae-web run dev
curl -s http://127.0.0.1:5217/
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed targeted result:

```text
Python static regression: 6 passed
Node Web regression: 9 tests passed
JavaScript syntax check: pass
dev-server HTTP smoke: http_status=200 with Slice 0217 and upload-surface-panel
```

Observed full quality gate:

```text
1627 passed, 1 warning
statement_coverage=97.98% threshold=95.00%
branch_coverage=93.73% threshold=85.00%
contract_validation=pass schemas=47 examples=76 negative_examples=52 openapi=7
ae_document_detail_postgres_smoke=skipped reason=NEX_AE_DOCUMENT_DETAIL_POSTGRES_SMOKE
```
