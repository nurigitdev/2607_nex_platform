# Slice 0456: AE Web Artifact Lifecycle Action State

## Goal

Add browser-side lifecycle action state and action availability rules before
rendering lifecycle controls in the AE Web shell.

## Scope

- Added `apps/nex-ae-web/src/artifactLifecycleActionState.js`.
- Added status-aware action sets for `ARCHIVE`, `RESTORE`, and
  `MARK_DELETED`.
- Added lifecycle action context, running, success, failure, and summary state
  builders using the shared AE Web operation-state model.
- Kept raw comments, storage refs, rendered payloads, credentials, provider
  endpoints, and database URLs out of lifecycle state and summaries.

## Evidence

- `node --test apps/nex-ae-web/test/artifactLifecycleActionState.test.mjs`
  - `5 passed`
- `npm --prefix apps/nex-ae-web test`
  - `232 passed`

## Notes

- `READY`, `DRAFT`, and `FAILED` artifacts can be archived or logically
  deleted.
- `ARCHIVED` artifacts can be restored or logically deleted.
- `DELETED` artifacts can be restored.
- `RENDERING` artifacts expose no enabled lifecycle actions.
