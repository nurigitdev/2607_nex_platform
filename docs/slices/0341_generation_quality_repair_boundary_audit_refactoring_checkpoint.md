# Slice 0341: Generation Quality Repair Boundary Audit/Refactoring Checkpoint

## Scope

Start S35 by freezing the repair-loop boundary after AE user feedback and AG
operator disposition have been recorded.

This slice does not execute a repair yet. It records which service owns each
part of the loop and keeps the storage policy explicit before remediation tasks
are persisted.

## Implemented

- Added `ag_generation_remediation_boundary_decision.v1`.
- Declared canonical owner services:
  - AG owns remediation orchestration and operator task state;
  - CX owns generation lineage and repair execution;
  - AE API owns user feedback intake;
  - MO owns model-provider execution.
- Declared the S35 storage policy:
  - safe fields are IDs, refs, hashes, short previews, status, result refs, and
    metadata;
  - raw prompt, raw generation output, raw source text, raw feedback comment,
    raw operator note, and credential material are not stored.
- Declared the remediation status transition policy from `PROPOSED` through
  terminal states.
- Added regression coverage for owner assignments, invalid decision shapes,
  sensitive-key detection, and status-transition checks.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation_boundary.py -q
9 passed
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2333 passed, 1 warning
statement_coverage=98.52% threshold=95.00%
branch_coverage=95.56% threshold=85.00%
contract_validation=pass schemas=55 examples=87 negative_examples=64 openapi=7
```

Next slices:

```text
Slice 0342: remediation action contract/schema foundation
Slice 0343: AG remediation candidate projection rules
Slice 0344: AG remediation task API/repository foundation
Slice 0345: remediation PostgreSQL smoke evidence
```
