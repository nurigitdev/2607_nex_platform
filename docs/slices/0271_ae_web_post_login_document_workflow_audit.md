# Slice 0271: AE Web Post-Login Document Workflow Audit

## Scope

Audit the AE Web post-login document workflow before adding authenticated upload
behavior. This slice freezes the current structure after the credential-login
Playwright PostgreSQL smoke and records the intended Slice 0272-0274 path.

## Implemented

- Added `scripts/smoke/run_ae_web_post_login_document_workflow_audit.py`.
- The audit verifies:
  - AE Web upload, document detail, retrieval, client registry, and main
    orchestration files are present.
  - Required post-login HTML anchors exist for login, upload, document list,
    document detail, and retrieval panels.
  - Upload metadata remains a browser-safe handoff and does not include source
    bytes.
  - Fetch upload uses same-origin browser credentials.
  - Owner scope is derived from OA session claims after login.
  - AE API upload facade stays browser-user authenticated and delegates CX
    registration through service auth.
- Recorded planned non-blocking gaps for:
  - Slice 0272 file metadata input surface.
  - Slice 0274 authenticated upload Playwright PostgreSQL smoke.
- Added the audit to the default quality gate.

## Decisions

- Keep Slice 0272-0274 on metadata handoff first. Raw file bytes and CX storage
  expansion remain deferred until that boundary is explicitly opened.
- Browser calls continue through same-origin `/ae-api`; backend targets and
  service credentials stay server-side.
- Any enabled upload smoke must connect to real `nex_ae_test`, `nex_oa_test`,
  and `nex_cx_test` databases and keep evidence redacted.

## Evidence

- Audit summary:
  `./.venv/bin/python scripts/smoke/run_ae_web_post_login_document_workflow_audit.py --summary`
- Targeted regression:
  `./.venv/bin/pytest tests/test_ae_web_post_login_document_workflow_audit.py -q`
- Runner coverage:
  `./.venv/bin/pytest tests/test_ae_web_post_login_document_workflow_audit.py --cov=run_ae_web_post_login_document_workflow_audit --cov-branch --cov-report=term-missing -q`

## Next

Slice 0272 should harden the AE Web authenticated upload metadata surface by
adding an explicit browser file metadata input and updating the safe upload
preview without introducing raw source content into evidence.
