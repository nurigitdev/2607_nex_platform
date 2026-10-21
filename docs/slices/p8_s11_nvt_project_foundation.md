# P8-S11: NVTProject Foundation

Completed on 2026-10-21. NeX-EOS now persists `NVTProject` as a separate
top-level business object rather than treating it as an ordinary Project row.

## Scope

- Added migration `2503_eos_nvt_project`.
- Added tenant-scoped NVTProject create, read, active-only read, and optimistic
  update operations.
- Wired the project repository into the EOS runtime whenever its database
  runtime is configured.
- Kept ordinary Project hierarchy, traversal, NVT economic/token semantics,
  and public domain routes outside this Slice.

## Contract

`nvt_project_id` is the immutable stable identity. `nvt_project_code` is unique
inside one tenant and is not used as a cross-tenant identity. New records start
at version 1. Name or active/inactive state updates require an exact
`expected_version` and increment the version atomically; stale writers fail
with `EOS_NVT_PROJECT_VERSION_CONFLICT`.

The same ID and code may exist independently in different tenants. Every read
and update is tenant-qualified, and the active-only projection never returns an
inactive NVTProject.

## Verification

- EOS S07-S11 Slice Gate: `103 passed`, 4 protected PostgreSQL skips.
- EOS statement coverage: `100%`; branch coverage: `100%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Actual dev/test PostgreSQL migration applied `2503` after `2500`-`2502`.
- Protected S11 smoke connected as `nex_eos_user@nex_eos_test` and verified
  tenant isolation, active filtering, optimistic version conflict, and final
  zero residue.
- Remote model providers were not required.

The requested repository-wide Checkpoint Gate was executed after the S11
implementation. It exposed pre-existing global baseline drift caused by the
new EOS service inventory and an older readiness test-double signature. Those
issues are isolated to P8-S11A and do not change this NVTProject contract.
