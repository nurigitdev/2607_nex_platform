# Platform AG Cross-Service Trace Operations Runbook

## Preconditions

- Use only the OA, AE, CX, MO, and AG test database profiles.
- Apply all five service migration chains before protected execution.
- Provide an OA-admitted AG service identity with `service:call` and
  `operations:read` for every source API.
- Keep source-service API routing enabled. Direct cross-service database reads
  and private storage access are prohibited.
- Remote embedding, reranking, and generation providers are not required to
  reconstruct already persisted lifecycle metadata.

## Protected Command

Set `NEX_S138_AG_TRACE_POSTGRES_SMOKE=1`, provide the five service-local test
database URL environment values through the local secret mechanism, and run:

```bash
./.venv/bin/python scripts/smoke/run_platform_ag_trace_postgres_smoke.py --summary
```

Never place connection strings or credentials in shell history, evidence
documents, issue comments, or committed configuration.

## Expected Evidence

The successful summary is:

```text
platform_ag_trace_postgres_smoke=pass checks=9/9 services=5 families=8 residue=0 next=1381
```

Confirm that the five source statuses are `READY` and that the timeline includes
`AUTH`, `UPLOAD`, `INGESTION`, `RETRIEVAL`, `GENERATION`, `ARTIFACT`, `ACCESS`,
and `OPERATIONS`. The result must also report actual PostgreSQL, service-API
transport, restart-safe AG audit evidence, and no private payload.

## Source Failure Triage

Use the bounded source status and failure code to identify the owning service.
Check that service's migration head, process readiness, route admission, and
service token audience/scopes. Do not replace an unavailable source with a
cross-service database read. Healthy source stages remain available while the
failed source is represented as `DEGRADED` or `UNAVAILABLE`.

For CX projection failures, verify UUID result normalization as well as
ingestion, retrieval, and generation trace columns. For AE, verify upload,
response, artifact, render, and metadata-only access audit records. For OA and
MO, verify their service-owned authentication/trust and provider-operation
event stores.

## Audit And Restart Verification

Every successful AG trace read must append an
`ag.cross_service_trace.read.succeeded` event before returning the projection.
Dispose and reopen the AG store, then verify exactly one event for the smoke
trace. Artifact preview and download access must emit durable metadata-only audit
events. If either AG trace-read or AE access audit persistence is unavailable,
the request must fail closed.

## Cleanup Verification

The runner deletes its AG, MO, AE, CX, and OA fixtures in dependency order and
reports one residue count per service. Every value must be zero. If execution
fails during seeding, the finally cleanup begins from the first attempted seed.
Investigate only identifiers with the dedicated `s138` fixture prefix; never
delete unrelated test records.

## Rollback And Fail-Closed

- Disable the protected runner by removing its opt-in flag.
- Keep the last accepted redacted contract and source API versions active.
- Do not bypass a failed audit write, invalid source contract, missing scope,
  owner boundary, or private-field rejection.
- Preserve partial-source diagnostics and return bounded operation metadata
  only. Do not synthesize successful stages for unavailable services.

## Privacy And Secret Handling

AG may retain opaque correlation identifiers, owner digests, lifecycle state,
timestamps, safe model aliases, and bounded failure codes. It must not retain
prompts, source or evidence text, generated text, structured drafts, vectors,
tokens, credentials, provider endpoints, database locations, storage
references, or absolute paths. Logs and evidence must use redacted environment
names and counts only.

## S139 Handoff

S139 may consume the protected AG trace API, safe stage status, public
correlation identifiers, and owner-authorized AE links for Korean-default
Playwright acceptance. It may not consume AG database rows, another service's
database, private storage, or any service-private audit payload.
