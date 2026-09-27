# Slice 1004: AE persistence gap re-baseline

## Goal

Reclassify each AE runtime state holder as PostgreSQL-ready, delegated to its
real system of record, or an explicit durability gap.

## Decision

- Six surfaces have active PostgreSQL adapters: chat interactions, artifact
  metadata, generation feedback, repaired-response handoffs and decisions, and
  scheduler/worker operations.
- Document-library state remains CX-owned and browser sessions remain OA-owned;
  AE must not duplicate either system of record.
- Workspace, upload handoff, retrieval interaction, and recovery request stores
  require schema-and-adapter decisions before durable implementation.
- Prompt analytics and prompt registry already have tables but still use
  in-memory runtime stores, so they are adapter gaps rather than schema gaps.
- Rendered artifact payloads remain outside PostgreSQL. Production-like runtime
  requires `NEX_AE_ARTIFACT_STORAGE_ROOT`; otherwise the adapter is in-memory.
- Slice 1004 records seven gaps but adds no migration or table.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_ae_persistence_gap_rebaseline.py --summary
./.venv/bin/pytest -q tests/test_ae_persistence_gap_rebaseline.py \
  --cov=nex_ae_api.persistence_audit \
  --cov=run_ae_persistence_gap_rebaseline \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
rebaseline: PASS, surfaces=15, postgres_ready=6, delegated=2, gaps=7, issues=0
focused tests: 6 passed
new module statement/branch coverage: 100%
Slice Gate: 1,870 passed, 1 known warning
statement coverage: 97.72%
branch coverage: 95.40%
contract validation: 92 schemas, 145 examples, 109 negative examples, 7 OpenAPI
```
