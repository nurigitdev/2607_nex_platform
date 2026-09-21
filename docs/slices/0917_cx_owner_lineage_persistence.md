# Slice 0917: CX Owner-Scoped Lineage Persistence

## Scope

This slice adds the durable ownership lineage contract for CX jobs, document
processing runs, retrieval packages, generation executions, and remediation
attempts. The canonical lineage is derived from the authenticated
`CxAccessContext` and uses `oa.tenant` plus `oa.user` references.

## Decisions

- Existing lineage tables gain nullable canonical owner columns so historical
  rows remain readable while known document-backed rows are backfilled.
- New writes inherit document ownership through database triggers. Retrieval
  evidence from different owners is rejected instead of producing a mixed
  package. Migration also stops if mixed-owner historical evidence already
  exists, leaving the transaction unapplied for explicit remediation.
- `cx_generation_executions` stores status, hashes, safe runtime metadata,
  usage, and recovery lineage only. Prompts, messages, output previews, raw
  output, chunk text, summary text, and vectors are excluded.
- Owner-scoped indexes use short names and put tenant and owner identifiers
  before time columns.
- Runtime route wiring is deferred to Slice 0918. Actual migration and CRUD
  verification against `nex_cx_test` is reserved for Slice 0919.

## Evidence

Run the deterministic contract evidence:

```bash
PYTHONPATH="services/_shared:services/nex-cx:scripts/smoke" \
  ./.venv/bin/python scripts/smoke/run_cx_owner_lineage_persistence_contract.py --summary
```

The evidence verifies all lineage targets, backfills, triggers, bounded SQL
identifier lengths, metadata-only generation DDL, owner-scoped indexes, and a
private-payload-free generation persistence projection.

DGX Spark is not required for this slice because no model provider is invoked.
