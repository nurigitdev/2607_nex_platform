# Slice 0200: CX Upload Ownership Resolver Guardrail Smoke

## Scope

Slice 0200 adds a CX-side defense-in-depth guardrail for upload ownership refs
and protected PostgreSQL smoke evidence against the CX test database.

Implemented:

- CX upload route accepts an injectable ownership resolver.
- `NEX_CX_UPLOAD_OWNER_RESOLVER_MODE` controls runtime behavior.
- supported modes: `disabled` and `verify`.
- default mode remains `disabled` so existing mock-first regression flows keep
  working without a live OA service.
- in `verify` mode, CX resolves `ownership_ref` before writing source file,
  content object, ACL, or local source materialization metadata.
- resolver failures are returned as `cx.upload_owner_unresolved`, and CX does
  not persist upload rows when ownership resolution fails.
- `scripts/smoke/run_cx_upload_ownership_postgres_smoke.py` performs guarded
  migration refresh, route-backed upload, persisted ownership/ACL checks, and
  cleanup against the CX `test` profile.
- the default quality gate calls the smoke in skipped mode, and
  `run_postgres_test_smoke_suite.py` includes it in the opt-in suite.

## Runtime Modes

```text
disabled  skip OA resolver calls
verify    require existing tenant/user refs in OA before CX upload persistence
```

The default resolver uses:

```text
NEX_OA_BASE_URL
NEX_CX_TO_OA_SERVICE_TOKEN
NEX_OA_SUBJECT_RESOLVER_TIMEOUT_SECONDS
```

## PostgreSQL Smoke

The protected smoke requires:

```bash
NEX_CX_TEST_DATABASE_URL=postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test \
NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_cx_upload_ownership_postgres_smoke.py --summary
```

The smoke runs CX migrations first, uses the service API path, verifies
`cx_content_objects` owner ref columns plus the owner ACL ref columns, checks
that the local source file was checksum-verified, and deletes its smoke rows.

## Privacy Boundary

Smoke evidence and API responses expose only stable IDs, hashes, storage
metadata, and boolean checks. They do not expose raw source text, source bytes,
tokens, provider endpoints, database passwords, or raw identity profiles.

## Next Slice

Recommended next slice:

- `0201_cx_owner_scoped_document_library_projection`

That slice should expose owner-aware document list/read projection behavior now
that upload ownership refs are persisted and optionally verified.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_ingestion.py tests/test_smoke_helpers.py -q
```

Observed targeted result:

```text
242 passed
```

Protected PostgreSQL smoke:

```bash
NEX_CX_TEST_DATABASE_URL=postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test \
NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE=1 \
./.venv/bin/python scripts/smoke/run_cx_upload_ownership_postgres_smoke.py --summary
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed protected smoke result:

```text
cx_upload_ownership_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL
```

Observed protected smoke checks:

```text
api_status_created=true
runtime_mode=true
resolver_called_once=true
resolver_verify_only=true
persisted_content_owner_refs=true
persisted_owner_acl_ref=true
source_checksum_verified=true
source_file_path_materialized=true
raw_payload_absent=true
redacted_database_url=postgresql+psycopg://nex_cx_user:***@127.0.0.1:5432/nex_cx_test
```

Observed full quality gate:

```text
1549 passed
statement_coverage=97.88%
branch_coverage=93.43%
contract_validation=pass
cx_upload_ownership_postgres_smoke=skipped reason=NEX_CX_UPLOAD_OWNERSHIP_POSTGRES_SMOKE
```
