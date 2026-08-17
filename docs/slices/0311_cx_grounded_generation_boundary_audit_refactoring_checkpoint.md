# Slice 0311: CX Grounded Generation Boundary Audit and Refactoring Checkpoint

## Scope

Define a raw-safe CX grounded generation admission boundary before adding the
next generation-quality guards.

This slice does not change external API behavior, database schema, or remote
provider execution. The office-network protected live smoke was run before this
slice and confirmed that embedding, reranker, generation, and PostgreSQL live
RAG wiring are reachable.

## Implemented

- Added `cx_grounded_generation_boundary_audit.v1`.
- Extracted the grounded generation admission decision into
  `evaluate_grounded_generation_boundary`.
- Kept `validate_generation_request` as the legacy entrypoint, now backed by
  the new decision helper.
- Captured stage status for:
  - compatibility rule selection;
  - retrieval package reference validation;
  - retrieval package store availability;
  - retrieval package lookup;
  - package hash match;
  - package status readiness;
  - selected evidence membership.
- Added raw-safe request, compatibility, retrieval reference, retrieval package,
  source count, score summary, and warning-kind summaries.
- Added redaction assertions so audit output excludes raw prompts, messages,
  source/evidence text, query text, provider endpoints, storage paths, and
  vectors.
- Marked the next guard slot as `retrieval_package_quality` for Slice 0312.

## Boundary Statuses

```text
GROUNDING_NOT_REQUIRED
GROUNDED_ADMITTED
GROUNDED_BLOCKED
```

## Refactoring Checkpoint

The CX generation route still returns the same success and problem responses.
The useful change is internal: future guards can now read a single decision
surface instead of re-implementing grounded-generation readiness checks.

Recommended next slice:

```text
Slice 0312: CX retrieval package quality guard for generation requests
```

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_cx_generation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted result:

```text
31 passed, 1 warning
```

Observed full quality gate:

```text
2142 passed, 1 warning
statement_coverage=98.50% threshold=95.00%
branch_coverage=95.27% threshold=85.00%
contract_validation=pass schemas=50 examples=81 negative_examples=56 openapi=7
```
