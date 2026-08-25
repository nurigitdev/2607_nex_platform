# Slice 0343: AG Remediation Candidate Projection Rules

## Scope

Turn S34 feedback/disposition rollup items into S35 remediation candidates using
the action contract from Slice 0342.

This slice does not persist tasks yet. It produces deterministic candidate
actions that the next API/repository slice can store or expose.

## Implemented

- Added `ag_generation_remediation_candidate_projection.v1`.
- Reused `ag_generation_remediation_action.v1` for every candidate action.
- Added candidate rules for:
  - citation quality signals -> `citation_repair`;
  - retrieval/no-answer/grounding signals -> `retrieval_repair`;
  - metadata/generation quality signals -> `retry_generation`;
  - negative feedback without quality detail -> `operator_followup`;
  - escalation -> `prompt_policy_review`.
- Added source refs from AG quality, AE feedback, and AG operator disposition.
- Added deterministic priority selection:
  - `ERROR` or escalated -> `URGENT`;
  - repeated negative feedback or in-progress disposition -> `HIGH`;
  - otherwise `NORMAL`.
- Kept candidate evidence limited to generated hashes and short previews.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation.py -q
30 passed
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2363 passed, 1 warning
statement_coverage=98.54% threshold=95.00%
branch_coverage=95.64% threshold=85.00%
contract_validation=pass schemas=56 examples=88 negative_examples=65 openapi=7
```

Next slices:

```text
Slice 0344: AG remediation task API/repository foundation
Slice 0345: remediation PostgreSQL smoke evidence
```
