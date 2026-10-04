# Platform Authenticated Document Ingestion Operations

## Preconditions

- Run only against the five service-owned `*_test` databases.
- Supply all five test database URLs through the operator environment. Never
  commit connection values or place them in evidence output.
- Confirm the selected loopback ports are free and the test storage root is
  writable. The runner creates a unique temporary root and removes it.
- Keep OA-backed session mode and signed service admission enabled. Do not
  substitute mock user claims in this protected journey.

## Protected Command

```bash
export NEX_PLATFORM_AUTHENTICATED_INGESTION_POSTGRES_SMOKE=1
./.venv/bin/python scripts/smoke/run_platform_authenticated_ingestion_postgres_smoke.py --summary
```

Database credentials must come from the operator's secret environment. The
command must not contain passwords, tokens, provider keys, or private source
content.

## Expected Evidence

The success summary is:

```text
platform_authenticated_ingestion_postgres=pass databases=5 restart=2 index=ready residue=0 next=1351
```

A pass means OA credential login, AE upload, signed AE-to-CX handoff, durable
CX worker execution, mock MO embedding, lexical/vector readiness, API restart,
unauthenticated denial, cross-owner hiding, and cleanup all passed through
actual loopback HTTP and PostgreSQL boundaries.

## Failure Triage

1. `configuration_invalid` or early `execution_failed`: verify all five test
   database targets, roles, migration permissions, and loopback port
   availability. Never substitute a development or production database.
2. Readiness timeout: stop the run and inspect the named local service. Keep
   PostgreSQL persistence and signed admission enabled.
3. Upload or progress authorization failure: verify OA session introspection,
   the AE browser cookie, and AE's audience-bound CX service token. Do not
   accept caller-supplied owner aliases.
4. Worker failure: inspect only error code, step, attempt, checkpoint, and
   correlated request identifiers. Do not log source, Markdown, chunk text,
   vectors, or prompt content.
5. Vector readiness mismatch: verify the MO `test` mock capability, persisted
   vector count, fingerprint, and CX freshness state. Live DGX connectivity is
   intentionally outside S135.
6. Any accepted unauthenticated or cross-owner read is a blocking privacy
   failure. Isolate the test environment before retrying.

## Cleanup Verification

The runner stops all subprocesses and invokes AE, CX, OA, and temporary-file
cleanup from `finally`, including failures before `INDEX_READY`. Verify counts
without selecting payload-bearing columns:

```sql
-- nex_ae_test
SELECT count(*) FROM ae_upload_handoffs WHERE request_id LIKE 's135-%';

-- nex_cx_test
SELECT count(*) FROM service_jobs WHERE request_id LIKE 's135-%';
SELECT count(*) FROM cx_content_objects WHERE original_filename LIKE 's135-%.md';
SELECT count(*) FROM cx_prompt_render_events WHERE request_id LIKE 's135-%';

-- nex_oa_test
SELECT count(*) FROM oa_auth_events WHERE request_id LIKE 's135-%';
SELECT count(*) FROM service_operational_events WHERE request_id LIKE 's135-%';
```

Also confirm no `/tmp/nex-s135-*` directory remains. If residue exists, stop
all smoke processes and remove only rows carrying that run's unique S135
prefix after reviewing foreign-key order and source-file references.

## Rollback And Fail-Closed

- Stop the CX worker, AE, CX, MO, then OA. Do not retry while a prior worker or
  API generation remains alive.
- Keep OA session mode and signed-only service admission enabled. OA, CX, MO,
  or persistence dependency failure must remain `401`, `403`, `502`, or `503`;
  it must not fall back to local owner defaults or memory persistence.
- Treat a partial index as unavailable. Retrieval must not consume an index
  unless status and freshness are `READY`, vector counts match, and
  `retrieval_usable` is true.
- Remove test-prefixed rows and temporary storage before rerunning.

## Privacy And Secret Handling

Evidence may contain bounded status, count, reason-code, request, trace, and
opaque resource identifiers. It must not contain source text, extracted
Markdown, chunk text, summaries, vectors, absolute storage paths, browser
session values, passwords, service tokens, database URLs, or provider secrets.

## Remote Provider Boundary

S135 uses MO's deterministic protected `test` mock embedding capability.
Remote embedding, reranking, and generation providers are outside S135 and are
not required. S136 requires actual embedding and reranker provider evidence for
permission-filtered hybrid retrieval.
