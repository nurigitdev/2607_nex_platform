# P8-S13: NVT Aggregation and Project Resolution

Completed on 2026-10-21. NeX-EOS now resolves both directions of the initial
NVT hierarchy read model without adding a denormalized hierarchy table.

## Scope

- Added a tenant-scoped recursive query from NVTProject to all Mother Projects
  and descendants.
- Added descendant-to-NVT resolution through the Mother ancestor.
- Bounded recursion to the admitted three Project levels.
- Bounded result projection to 1..1,000 rows, with a default of 500.
- Kept missing, empty, and cross-tenant NVT scopes non-leaking.

No database migration was required. The query uses the authoritative
`eos_project` hierarchy introduced by P8-S12.

## Verification

- Focused S12/S13 regression: 25 passed.
- Protected PostgreSQL smoke connected to `nex_eos_test`, exercised recursive
  traversal and reverse resolution, and left zero Project residue.
- EOS Slice Gate: 128 passed, 6 protected skips.
- EOS statement coverage: 99.76%; branch coverage: 100%.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Remote model providers were not required.
