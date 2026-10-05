# Slice 1364: CX Grounded Generation Runtime Composition

## Goal

Use one owner-scoped retrieval package store for synchronous and asynchronous
grounded generation while preserving the local mock fallback.

## Implementation

- PostgreSQL `CxMvpRuntimeComposition` now owns the restart-safe retrieval
  package store from Slice 1363.
- CX startup selects that durable store for both `/api/v1/generations` and
  `/api/v1/generation-jobs`; memory mode retains `ContentIngestionStore`.
- The authenticated `CxAccessContext` reaches the retrieval store before private
  evidence is read. Retrieval context reads use the same rule.
- Materialization failures become explicit CX problem responses with retry
  semantics rather than uncaught server errors.
- Sync and async tests prove owner context propagation and shared composition.

## Verification

```bash
scripts/quality/run_slice_gate.sh \
  --service nex-cx \
  --test tests/test_cx_grounded_generation_runtime_composition.py \
  --coverage-target scripts/smoke/run_cx_grounded_generation_runtime_composition.py \
  --smoke scripts/smoke/run_cx_grounded_generation_runtime_composition.py
```

This Slice does not require PostgreSQL or a remote provider. Protected runtime
evidence remains assigned to Slice 1370. Slice 1365 binds citation validation
and bounded repair to this composed package lineage.

Observed evidence:

- Slice Gate: `2,408 passed`
- repository statement coverage: `99.09%`
- repository branch coverage: `98.20%`
- composition evidence statement/branch coverage: `100%`/`100%`
- contract validation: `161` schemas, `220` examples, `188` negative
  examples, and `7` OpenAPI documents
- deterministic composition evidence: `9/9` checks
