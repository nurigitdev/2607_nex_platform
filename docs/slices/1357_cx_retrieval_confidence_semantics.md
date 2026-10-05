# Slice 1357: CX Retrieval Confidence Semantics

## Goal

Make READY, LOW_CONFIDENCE, and NO_ANSWER a single deterministic decision
instead of parallel status and score-summary calculations.

## Implementation

- Added the versioned `cx_retrieval_confidence_v1` policy.
- Kept the frozen low-confidence threshold at `0.2` and made equality
  inclusive: a best score of exactly `0.2` is READY.
- Classified an empty permission-admitted evidence set as NO_ANSWER without
  invoking the reranker or private evidence materializer.
- Classified non-empty evidence below `0.2` as LOW_CONFIDENCE.
- Projected the policy ID, reason, best score, threshold, and evidence count
  from one confidence decision into the package score summary.
- Used the maximum final score rather than relying on evidence order.

Permission denial remains a generic non-retryable 404 and never becomes a
NO_ANSWER package. No table, migration, route, or provider call was added.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_cx_retrieval_confidence_acceptance.py \
  --coverage-target services/nex-cx/nex_cx/hybrid_retrieval_package.py \
  --coverage-target scripts/smoke/run_cx_retrieval_confidence_acceptance.py \
  --smoke scripts/smoke/run_cx_retrieval_confidence_acceptance.py
```

Observed result: `2339 passed`; statement coverage `99.06%`, branch coverage
`98.17%`, changed acceptance script 100%, and changed package branch coverage
100%.
