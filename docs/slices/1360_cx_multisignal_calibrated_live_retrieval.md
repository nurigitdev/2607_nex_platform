# Slice 1360: CX Multi-Signal Calibrated Live Retrieval

## Goal

Replace the unsafe native-reranker threshold with an evidence-backed
multi-signal confidence decision that remains fail-closed across embedding,
reranker, and ranking-policy changes.

## Implementation

- Added `cx_retrieval_confidence_multisignal_v1` with weights:
  reranker score `0.20`, reranker margin `0.10`, normalized weighted-RRF score
  `0.40`, and BM25/vector channel support `0.30`.
- Added hash-bound CANDIDATE, ACTIVE, and RETIRED calibration profiles bound to
  embedding model revision, reranker model revision, weighted-RRF policy, and
  feature schema.
- Changed calibrated runtime admission so missing, changed, ambiguous, or
  tampered profiles return LOW_CONFIDENCE and cannot promote a result to READY.
- Preserved NO_ANSWER for an empty permission-admitted candidate set.
- Included confidence profile ID/hash and feature schema in metadata-only
  operations evidence without query text, private chunks, vectors, endpoints,
  credentials, or individual calibration samples.
- Kept the deterministic legacy confidence path available for existing mock
  regression tests; protected runtime explicitly enables calibration-required
  mode.

No database table or migration was added. Runtime composition accepts profiles
through an explicit dependency so a model replacement requires a new evaluated
profile rather than a source-code threshold change.

## Protected Live Evidence

The protected run used actual `nex_cx_test`, `Qwen3-Embedding-4B`, and
`Qwen3-Reranker-4B` through the CX production retrieval composition.

- 20 calibration queries: 10 READY and 10 LOW_CONFIDENCE judgments
- selected threshold: `0.7050041`
- false-READY rate: `0.0`
- READY recall and precision: `1.0`
- holdout READY score: `0.8146452`
- holdout LOW_CONFIDENCE score: `0.5933478`
- provider calls: embedding `24`, reranking `22`, failures `0`
- protected checks: `17/17 PASS`
- PostgreSQL migrations: `21` planned, `21` current
- restart readback: all `23` hash-only retrieval packages
- denied owner: `404` with no provider-count increase
- cleanup: source, content, vector, retrieval, and event fixtures absent

Minor floating-point variation between live runs changes the candidate profile
hash and threshold slightly. Activation therefore uses the complete evaluated
profile and its hash, never a copied numeric threshold.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_retrieval_confidence_calibration.py \
  --test tests/test_nex_cx_hybrid_ranking.py \
  --test tests/test_nex_cx_hybrid_retrieval_package.py \
  --test tests/test_nex_cx_hybrid_retrieval_runtime.py \
  --test tests/test_nex_cx_mvp_runtime.py \
  --test tests/test_nex_cx_retrieval_observability.py \
  --test tests/test_s136_permission_hybrid_live_postgres_smoke.py \
  --coverage-target services/nex-cx/nex_cx/retrieval_confidence_calibration.py \
  --coverage-target scripts/smoke/run_s136_permission_hybrid_live_postgres_smoke.py \
  --smoke scripts/smoke/run_s136_permission_hybrid_live_postgres_smoke.py
```

Protected live invocation requires
`NEX_S136_PERMISSION_HYBRID_LIVE_POSTGRES_SMOKE=1`, the actual
`NEX_CX_TEST_DATABASE_URL`, and live embedding/reranker endpoint credentials.
The default quality gate leaves this protected smoke skipped.

Slice Gate result:

- status: `PASS` (`172` selected tests, `108.726s`)
- CX statement coverage: `99.10%`
- CX branch coverage: `98.22%`
- calibration module statement/branch coverage: `100%` / `100%`
- protected smoke runner statement/branch coverage: `100%` / `100%`
- contract validation: schemas `161`, examples `219`, negative examples `188`,
  OpenAPI documents `7`

## Slice 1361 Handoff

Slice 1361 owns contract/runbook closure and the S136 Full Gate. It must retain
exact profile binding and fail-closed model drift, and must not promote the
Slice 1357 deterministic `0.2` regression threshold to a live policy.
