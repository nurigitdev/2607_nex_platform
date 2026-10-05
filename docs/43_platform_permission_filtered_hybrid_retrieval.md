# Platform Permission-Filtered Hybrid Retrieval Live Integration

Status: S136 complete through Slice 1361.

## Required Outcome

An OA-authenticated owner requests evidence for an S135 index-ready private
document through the protected CX retrieval API. CX must reject unauthorized
tenant or owner scope before reading lexical terms, vectors, or private chunk
text; obtain the query embedding through MO's live embedding route; collect
owner-filtered PostgreSQL BM25 and fresh pgvector candidates; apply weighted
RRF and the live reranker; classify READY, LOW_CONFIDENCE, and NO_ANSWER; and
persist only hash-bound, metadata-safe retrieval evidence.

## Retrieval Invariants

- OA claims remain the tenant and owner authority. Request payloads cannot
  broaden the authenticated scope.
- Permission admission precedes tokenization, BM25, pgvector, private text,
  and reranker input. Denied and missing documents are indistinguishable.
- PostgreSQL is the production candidate backend. BM25 uses `k1=1.2` and
  `b=0.75`; vector candidates require a payload-backed fresh READY index.
- Fusion uses vector weight `0.7`, BM25 weight `0.3`, and `rrf_k=60`.
- Reranking receives only permission-admitted, SHA-256-verified chunk text.
- The active live profiles are `Qwen3-Embedding-4B` and
  `Qwen3-Reranker-4B`; provider secrets, vectors, and private text are absent
  from stored and emitted evidence.
- A result is not promoted to READY unless an ACTIVE calibration profile
  exactly matches capability, model revision, request shape, score semantics,
  and retrieval policy. Unknown or changed models fail closed with
  CALIBRATION_REQUIRED. An empty admitted candidate set returns NO_ANSWER
  without invoking rerank.
- S136 does not reopen upload, extraction, chunking, or index publication.

## Current Gaps

All six boundary gaps are closed.

1. Slice 1360 consumed an S135-compatible owner-scoped index-ready document in
   the actual PostgreSQL/live-provider retrieval composition.
2. Live MO aliases, embedding/reranker model revisions, deployment identities,
   and request-path telemetry are asserted without endpoint or credential
   disclosure.
3. Denied owner scope returns the generic 404 before embedding, BM25, pgvector,
   private text, or reranker work and leaves provider counts unchanged.
4. Candidate-channel counts, weighted-RRF policy, reranker identity, and
   multi-signal confidence are captured by typed metadata-safe projections.
5. READY, LOW_CONFIDENCE, and NO_ANSWER were observed against `nex_cx_test`
   and the actual embedding/reranker providers.
6. Fresh-engine readback, hash-only persistence, residue-free cleanup, strict
   contracts, the operator runbook, and closure evidence bind the S137 handoff.

Slice 1353 closed the permission error propagation gap: mixed owner/tenant
scope now remains a generic non-retryable 404 across the package/API boundary,
before query embedding or either candidate channel can execute.

Slice 1354 aligned candidate lineage: PostgreSQL BM25 now reads only the latest
chunk set for each document, matching the source snapshot used by the pgvector
freshness guard. Protected test-database evidence rejects stale lexical terms.

Slice 1355 preserves query-embedding and reranker alias/model/deployment
identity in the retrieval profile while excluding endpoints, credentials, raw
vectors, and private payloads. Live model equality is assigned to Slice 1359.

Slice 1356 adds count-only candidate-channel evidence for weighted RRF and
freezes vector/BM25 weights `0.7/0.3` with `rrf_k=60` at the checkpoint gate.

Slice 1357 unifies READY, LOW_CONFIDENCE, and NO_ANSWER under the versioned
`cx_retrieval_confidence_v1` decision. Its inclusive `0.2` threshold remains a
deterministic regression baseline and is not accepted as a live-provider
calibration result.

Slice 1358 advances retrieval operations evidence to
`cx_retrieval_observability.v2`, exposing only confidence, channel counts,
safe provider identity, and classified failure-role metadata.

Slice 1359 adds model-agnostic calibration evaluation and exact model/profile
binding. A protected 36-sample Qwen3-Reranker-4B run rejected every single raw
score threshold under the false-READY and READY-recall constraints, so it
created no candidate profile and changed no runtime threshold.

Slice 1360 replaces the rejected raw-score decision with the approved
multi-signal policy. The profile combines reranker score and margin,
normalized weighted-RRF score, and BM25/vector channel support; it is bound to
both embedding and reranker model revisions plus ranking policy and feature
schema. Actual `nex_cx_test` and live-provider evidence calibrated 20 samples,
validated separate READY/LOW_CONFIDENCE queries, reloaded all 23 persisted
packages through a fresh engine, preserved pre-provider owner denial, and
removed all fixtures.

## Slice Sequence

| Slice | Scope |
| --- | --- |
| `1352` | Freeze the S136 boundary, gaps, live-provider requirement, and S137 handoff. |
| `1353` | Harden permission-first multi-document scope and denial evidence. |
| `1354` | Bind durable PostgreSQL BM25 and fresh pgvector candidate lineage. |
| `1355` | Freeze live embedding/reranker aliases, models, and request metadata. |
| `1356` | Harden weighted RRF and channel-contribution acceptance evidence; run Checkpoint Gate. |
| `1357` | Harden READY, LOW_CONFIDENCE, and NO_ANSWER decision semantics. |
| `1358` | Add metadata-only retrieval operations and provider-failure evidence. |
| `1359` | Add model-bound confidence calibration and reject unsafe threshold activation. |
| `1360` | Activate exact-model multi-signal calibration and prove PostgreSQL/live-provider integration, restart readback, denial isolation, and cleanup. |
| `1361` | Harden contracts/runbook, close S136, run Full Gate, and activate S137. |

## Slice 1361 Closure

- Hardened `cx_retrieval_context_package.v1` around canonical OA owner
  lineage, permission-first hybrid runtime identity, BM25/vector/RRF evidence,
  exact calibration profile binding, and READY/LOW_CONFIDENCE/NO_ANSWER state
  invariants.
- Added indexed calibrated READY and NO_ANSWER examples while retaining raw
  token and calibration-secret negative coverage.
- Added the protected operations runbook for execution, model replacement,
  recalibration, triage, cleanup, rollback, privacy, and S137 handoff.
- Replayed six deterministic S136 evidence components and retained the three
  database/provider components as explicit protected opt-ins during Full Gate.
- Recorded the actual Slice 1360 PostgreSQL/live-provider result rather than
  repeating protected mutation inside ordinary regression.
- Passed the final contract inventory (`161` schemas, `220` examples, `188`
  negative examples, and `7` OpenAPI documents), closure `13/13`, and Full
  Gate with `11,478 passed`, `31` policy-skipped protected tests, statement
  coverage `98.06%`, and branch coverage `96.99%`.

Completion signal: Met.

## Completion Signal

S136 is complete. Protected evidence against `nex_cx_test` and the actual
embedding/reranker providers proves permission-first BM25 plus pgvector
candidates, `0.7/0.3` weighted RRF, Qwen3-Reranker-4B reranking, confidence and
no-answer behavior, restart-safe hash-only persistence, denial isolation, and
zero fixture residue. Contract, runbook, closure, and Full Gate evidence are
bound to that result.

## S137 Handoff

S137 is the next active requirement. S137 may consume only an owner-scoped retrieval package with an
explicit READY, LOW_CONFIDENCE, or NO_ANSWER decision and complete provider,
permission, candidate, ranking, and evidence lineage. S137 owns generation,
citation validation, repair, and artifact lifecycle; S136 does not call the
generation provider.
