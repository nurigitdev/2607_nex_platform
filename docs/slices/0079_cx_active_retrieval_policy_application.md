# Slice 0079: CX active retrieval policy application

## Intent

Slice 0079 connects the AG retrieval policy registry to CX retrieval execution.
CX no longer treats its runtime defaults as an isolated hardcoded policy; it
maps the active registry record into `RetrievalQualityPolicy`.

## Runtime Behavior

- Requests with no `retrieval_policy` use the active registry policy.
- The current active registry policy remains `retrieval_quality_v1`.
- `retrieval_quality_v1` maps to the existing BM25 plus embedding-presence
  scoring behavior.
- `weighted_rrf_vector_bm25_v1` can still be selected explicitly in tests and
  smoke flows by `retrieval_policy.policy_id`.
- Registry `ranker`, `candidate_limits`, and `confidence` fields are converted
  through one CX parser path.

## Retrieval Package Evidence

Retrieval policy snapshots now include:

- `policy_id`
- `policy_version`
- `policy_hash`
- `policy_source`
- ranker weights
- candidate limits
- confidence threshold

Default retrieval packages use `policy_source = ag_registry_active`. Explicit
payload overrides use `policy_source = request_override`; if an override changes
registry defaults, the exact registry `policy_hash` is cleared so the package
does not imply an unchanged registry policy.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_cx_retrieval.py tests/test_nex_ag_retrieval_policies.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
