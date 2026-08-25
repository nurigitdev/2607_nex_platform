# Slice 0342: Generation Remediation Action Contract/Schema Foundation

## Scope

Freeze the first S35 remediation action contract so AG can turn feedback,
operator disposition, and generation-quality issues into safe repair tasks.

This slice does not persist or execute remediation actions yet. It defines the
record shape and domain builder that later slices must reuse.

## Implemented

- Added `ag_generation_remediation_action.v1`.
- Added the canonical action types:
  - `retry_generation`;
  - `retrieval_repair`;
  - `citation_repair`;
  - `prompt_policy_review`;
  - `operator_followup`;
  - `mark_accepted`.
- Added action status, priority, reason-code, owner, source-ref, result-ref,
  and evidence-summary fields.
- Kept free text redacted by contract:
  - evidence stores SHA-256 hashes and short previews only;
  - raw prompt, raw generation output, raw source text, raw feedback comment,
    and raw operator note flags are all fixed to `false`.
- Added a domain builder in `nex_ag.generation_remediation` for future
  candidate projection, API, and persistence slices.
- Added contract example and negative raw-output fixture.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation.py -q
20 passed
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=56 examples=88 negative_examples=65 openapi=7
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2353 passed, 1 warning
statement_coverage=98.52% threshold=95.00%
branch_coverage=95.57% threshold=85.00%
contract_validation=pass schemas=56 examples=88 negative_examples=65 openapi=7
```

Next slices:

```text
Slice 0343: AG remediation candidate projection rules
Slice 0344: AG remediation task API/repository foundation
Slice 0345: remediation PostgreSQL smoke evidence
```
