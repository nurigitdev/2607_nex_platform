# Slice 1016: AE Owner-Scoped Workspace API

## Goal

Make the workspace API restart-safe in production and enforce browser ownership
from authenticated OA claims without exposing cross-owner record existence.

## Implementation

- Workspace routes now use the shared AE facade authorization boundary, accepting
  service claims and browser user claims through one contract.
- Browser creation derives tenant and owner identifiers from the authenticated
  claim. Conflicting payload aliases or canonical references are rejected.
- Browser detail and activity reads compare the persisted owner and return the
  same not-found response for missing and cross-owner workspaces.
- Production composition selects `SqlAlchemyWorkspaceRepository` whenever the AE
  persistence runtime exposes an API session factory. The deterministic memory
  adapter remains available for isolated regression tests.
- Memory and SQL adapters now share `save_workspace` and
  `append_activity_record` operations, including idempotent activity behavior.
- The selected workspace store is exposed on `app.state.ae_workspace_store` for
  the later workspace-bound chat orchestration Slice.
- S101 ownership and coupling audits now recognize completed workspace hardening
  while keeping the remaining chat and artifact gaps visible.

This Slice uses SQLite and deterministic memory smoke evidence. It does not
mutate `nex_ae_test`; actual PostgreSQL proof remains scheduled for Slice 1020.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_workspace.py \
  --test tests/test_nex_ae_workspace_persistence.py \
  --test tests/test_ae_owner_scoped_workspace_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_persistence.py \
  --coverage-target scripts/smoke/run_ae_owner_scoped_workspace_api.py \
  --smoke scripts/smoke/run_ae_owner_scoped_workspace_api.py

scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_ae_workspace.py \
  --test tests/test_nex_ae_workspace_persistence.py \
  --test tests/test_ae_owner_scoped_workspace_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_persistence.py \
  --coverage-target scripts/smoke/run_ae_owner_scoped_workspace_api.py \
  --smoke scripts/smoke/run_ae_owner_scoped_workspace_api.py
```

Observed evidence:

- Focused regression: `33 passed` with one known Starlette warning.
- Slice Gate: `1948 passed`, statement `97.82%`, branch `95.56%`.
- Checkpoint Gate: `7548 passed`, statement `98.67%`, branch `96.57%`.
- Workspace API and repository coverage: statement at least `98.77%`, branch
  `100%`; deterministic smoke runner statement/branch `100%`/`100%`.
- Contract validation: 92 schemas, 145 positive examples, 109 negative
  examples, and 7 OpenAPI documents.
- Deterministic smoke: checks `8/8`, one owner-scoped workspace, one ordered
  creation activity, owner read accepted, cross-owner read hidden.
