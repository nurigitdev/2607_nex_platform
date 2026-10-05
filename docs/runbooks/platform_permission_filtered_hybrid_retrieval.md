# Platform Permission-Filtered Hybrid Retrieval Operations

## Preconditions

- Run only against `nex_cx_test` with the `nex_cx_user` test role.
- Supply the CX test database URL, embedding endpoint and credential, and
  reranker endpoint and credential through the operator environment. Never put
  their values in commands, documents, or evidence files.
- Confirm the configured embedding and reranker aliases resolve through MO and
  that their reported model revisions match the calibration profile binding.
- Keep PostgreSQL BM25 and pgvector enabled. The protected run must not replace
  either candidate channel with an in-memory implementation.
- Generation is outside S136 and must remain disabled for this run.

## Protected Command

```bash
export NEX_S136_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE=1
./.venv/bin/python \
  scripts/smoke/run_s136_permission_hybrid_live_postgres_smoke.py \
  --summary --output /tmp/s136-permission-hybrid-live-evidence.json
```

The operator environment supplies all connection values. The committed
command and generated evidence must not contain passwords, provider keys,
private source text, query text, vectors, or endpoint URLs.

## Expected Evidence

The success summary is:

```text
s136_permission_hybrid_live_postgres=pass checks=17/17 decisions=READY/LOW_CONFIDENCE/NO_ANSWER database=nex_cx_test providers=embedding,reranking
```

A pass means migrations were current, owner admission preceded all candidate
and private-text access, BM25 and pgvector both contributed, weighted RRF used
`0.7/0.3` with `rrf_k=60`, live reranking succeeded, multi-signal calibration
selected an ACTIVE exact-model profile, all three decisions were observed,
fresh-engine readback preserved hash-only packages, denied scope made no
provider call, and cleanup left no S136 fixture residue.

## Calibration And Model Changes

- A threshold is valid only inside its complete calibration profile. Do not
  copy a numeric threshold into configuration or source code.
- The ACTIVE profile must exactly match embedding model revision, reranker
  model revision, weighted-RRF policy, and feature schema.
- Any embedding, reranker, request-shape, score-semantics, ranking-policy, or
  feature change retires the old profile and requires a new candidate dataset,
  evaluation, holdout check, and activation decision.
- Missing, ambiguous, changed, or hash-invalid profiles must remain
  `LOW_CONFIDENCE`. They must never be promoted to `READY` by a fallback.
- `NO_ANSWER` is reserved for an empty permission-admitted candidate set and
  must not invoke reranking.

## Failure Triage

1. `configuration_invalid` or `target_not_allowed`: verify the test profile,
   test database identity, MO route configuration, and secret injection. Do
   not substitute a development or production database.
2. Migration or pool failure: stop the run, verify CX migration heads and pool
   disposal, then retry from a clean test connection.
3. Embedding failure: inspect safe capability alias, model revision, failure
   role, request id, and provider telemetry count. Do not log the query or
   vector.
4. BM25 or pgvector mismatch: verify current chunk-set lineage, lexical
   generation, vector payload fingerprint, and index freshness before
   rerunning.
5. Reranker failure: verify only permission-admitted text reached the provider
   and compare the safe model/deployment identity. Never replay foreign-owner
   text for diagnosis.
6. Calibration rejection: retain `LOW_CONFIDENCE`, inspect aggregate metrics
   and profile binding, and create a new evaluated candidate. Do not lower the
   threshold to make the smoke pass.
7. Any cross-owner visibility, provider-count increase after denial, private
   payload in evidence, or cleanup residue is a blocking privacy failure.

## Cleanup Verification

The runner removes source files through a temporary root and deletes S136 rows
from retrieval evidence/packages, vector payloads/indexes, lexical indexes,
chunks/chunk sets, extraction artifacts, source files, content objects, and
operational events in `finally`, including failed runs.

Verify only counts and hash-safe identifiers. Do not select private payload
columns. A successful run reports zero cleanup residue and a subsequent run
must not find packages from the previous probe.

## Rollback And Fail-Closed

- Disable protected execution by unsetting
  `NEX_S136_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE`.
- Retire the affected calibration profile when a provider model or ranking
  policy changes. Keep retrieval responses at `LOW_CONFIDENCE` until a new
  profile passes evaluation and holdout validation.
- If either candidate channel, freshness proof, reranker, persistence, or
  owner admission is unavailable, fail the request or return the defined
  non-READY state. Do not fall back to unfiltered search, process-local owner
  defaults, raw-score thresholds, or memory-only persistence.
- Rollback does not delete durable business data. It only removes S136 test
  fixtures and deactivates the invalid calibration profile.

## Privacy And Secret Handling

- Runtime retrieval responses may contain authorized query and evidence text
  for the calling owner, but persisted and operations evidence is hash-only and
  metadata-safe.
- Logs and evidence must not contain source text, chunk text, query text,
  vectors, matched private terms, document ids, endpoint URLs, database URLs,
  passwords, API keys, bearer tokens, or absolute storage paths.
- Denied and missing documents remain indistinguishable through the generic
  owner-scoped not-found response.
- Store temporary evidence only outside the repository and delete it after the
  closure decision is recorded.

## S137 Handoff

S137 may consume only an owner-scoped retrieval package that validates against
`cx_retrieval_context_package.v1`, carries a hash-bound READY,
LOW_CONFIDENCE, or NO_ANSWER decision, and preserves permission, provider,
candidate, ranking, calibration, and evidence lineage. S137 owns generation,
citation validation and repair, AE response lineage, and artifact lifecycle.
S136 never calls the generation provider.
