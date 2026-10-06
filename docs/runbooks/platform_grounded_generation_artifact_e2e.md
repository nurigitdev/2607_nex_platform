# Platform Grounded Generation And Artifact E2E Operations

## Preconditions

- Run only with the explicit test profile against `nex_ae_test` and
  `nex_cx_test`. The configured roles must own their respective databases.
- Apply current AE and CX migrations before starting the journey.
- Supply database URLs, live provider endpoints, provider credentials, and the
  browser executable through the operator environment. Never place their
  values in a command, document, report, or evidence file.
- Confirm MO resolves the configured embedding, reranking, and generation
  capability aliases. Model names and revisions may change; the journey must
  depend on capability and contract identity, not hard-coded model names.
- Keep the owner-private CX and AE storage roots outside the repository and
  writable only by the corresponding service runtime.

## Protected Command

```bash
export NEX_S137_GROUNDED_ARTIFACT_LIVE_POSTGRES_SMOKE=1
./.venv/bin/python \
  scripts/smoke/run_platform_grounded_generation_artifact_live_postgres_smoke.py \
  --summary
```

All connection and credential values are injected separately by the operator.
The default Full Gate deliberately leaves this flag unset and verifies a safe
SKIP after the actual protected result has been recorded in Slice 1370.

## Expected Evidence

The success summary is:

```text
platform_grounded_artifact_live=pass checks=8/8 providers=3 databases=2 residue=0
```

A pass means one authenticated and correlated browser request reached
permission-filtered retrieval, live embedding/reranking/generation, durable CX
generation, validated citation lineage, AE response persistence, artifact
admission, restart-safe rendering, owner preview/download, cross-owner denial,
and residue-free cleanup.

## Structured Draft Storage

- CX serializes the complete structured draft into owner-private storage.
- PostgreSQL retains only the opaque `cx-private://` reference, SHA-256, byte
  size, backend, and private schema version.
- A fresh CX runtime re-authorizes tenant and owner before reading and verifies
  the hash, size, JSON schema, generation id, and draft id.
- AE and AG treat the reference as opaque and never resolve CX private storage
  directly. A future object-storage adapter must preserve the same API and
  metadata contract.
- Missing, cross-owner, malformed, or integrity-invalid payloads must remain
  owner-scoped and fail closed.

## Failure Triage

1. Test-profile or database-identity failure: stop immediately and correct the
   operator environment. Never substitute a development or production DB.
2. Authentication or ownership failure: verify OA user claims and signed
   service audience/scope propagation. Do not add owner fallback values.
3. Retrieval rejection: inspect metadata-only permission, freshness, ranking,
   calibration, and failure-role evidence. Do not bypass LOW_CONFIDENCE or NO_ANSWER.
4. Provider failure: inspect MO capability alias, safe model/deployment
   identity, timeout role, request id, and aggregate telemetry. Never log the
   prompt, evidence, vector, or output.
5. Citation failure: retain the failed state and exact package lineage. Do not
   retry citation repair more than once or include invalid output in a repair
   prompt.
6. Structured-draft failure: verify only reference/hash/size metadata and the
   owner scope. Never print or move the private draft to PostgreSQL.
7. Artifact failure: inspect response binding, render-job state, and hashes.
   Do not expose storage paths or permit a cross-owner diagnostic read.
8. Any private payload in PostgreSQL/evidence or any cleanup residue is a
   blocking failure, even when the visible browser journey succeeded.

## Cleanup Verification

The protected runner removes its artifact render job, files, artifact and
handoff rows, AE chat/workspace rows, CX generation/retrieval/job rows, and
temporary private-storage roots in `finally` paths. Verify only aggregate
counts. A successful run reports zero for every AE/CX owner fixture and no
temporary artifact directory.

When a run fails, perform the same owner/run-scoped cleanup and prove absence
before retrying. Never delete unrelated owner data or broaden a cleanup query
to compensate for missing lineage.

## Rollback And Fail-Closed

- Disable protected execution by unsetting
  `NEX_S137_GROUNDED_ARTIFACT_LIVE_POSTGRES_SMOKE`.
- Roll back service activation, not durable business content. Existing private
  payloads remain subject to owner access and retention policy.
- If retrieval, provider execution, citation validation, private draft
  integrity, AE lineage, rendering, or owner admission is unavailable, keep
  the journey failed or pending. Do not substitute memory-only persistence,
  unfiltered retrieval, direct provider calls from AE, or public file paths.
- Model replacement requires current S136 calibration and MO alias readiness;
  it must not require a CX/AE storage schema change.

## Privacy And Secret Handling

- Logs, database projections, closure evidence, and exported diagnostics must
  not contain prompt, source, evidence, generated, or draft text.
- They also exclude vectors, bearer tokens, cookies, passwords, API keys,
  provider/database URLs, private storage references, and absolute file paths.
- Public artifact responses expose owner-safe preview/download links and
  hashes only. Cross-owner and missing resources remain indistinguishable.
- Store optional evidence files outside the repository and remove them after
  the closure decision is recorded.

## S138 Handoff

S138 consumes metadata-safe service API projections for the same trace. It may
correlate authentication, upload, ingestion, retrieval, generation,
citation/repair, AE response, artifact, and failure events, but may not read
service databases or private payload stores directly. AG must reconstruct the
operator timeline through service APIs and preserve every owner/privacy rule
closed by S137.
