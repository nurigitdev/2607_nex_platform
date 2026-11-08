# P8-S12: Project Hierarchy Foundation

Completed on 2026-10-21. NeX-EOS now persists ordinary Projects separately
from NVTProject and admits only bounded, tenant-scoped hierarchy shapes.

## Scope

- Added migration `2504_eos_project_hierarchy` and table `eos_project`.
- Added Mother and Child Project creation and tenant-scoped lookup.
- Enforced maximum ordinary Project depth 3.
- Enforced self-parent, ancestor-cycle, cross-tenant parent, and invalid NVT
  rejection before insert.
- Preserved a direct `nvt_project_id` only on Mother Projects; descendants
  derive NVT lineage through their ancestors.

Hierarchy links are immutable in this foundation Slice. This keeps newly
created trees acyclic by construction. The repository still walks the complete
ancestor chain and fails closed if it encounters pre-existing corrupt cyclic
data.

## Verification

- Focused hierarchy regression: 31 passed.
- Actual dev/test PostgreSQL migrations applied `2504`.
- Protected PostgreSQL smoke connected as `nex_eos_user@nex_eos_test`, verified
  depth 1/2/3, tenant isolation, migration identity, and zero residue.
- EOS Slice Gate: 120 passed, 5 protected skips.
- EOS statement coverage: 99.76%; branch coverage: 100%.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Remote model providers were not required.
