# Slice 0457: AE Web Artifact Lifecycle UX Wiring

## Goal

Wire the AE Web selected-artifact lifecycle controls to the browser artifact
client while keeping lifecycle state metadata-only.

## Scope

- Added selected artifact lifecycle controls to the artifact summary panel.
- Routed `ARCHIVE`, `RESTORE`, and `MARK_DELETED` clicks through the artifact
  client lifecycle action endpoint.
- Added browser state transitions for running, applied, and unavailable
  lifecycle actions.
- Reset lifecycle action state when the authenticated runtime, selected
  artifact, or generated artifact changes.
- Kept raw comments, rendered payloads, storage refs, provider endpoints,
  service tokens, and database URLs out of the browser surface.

## Evidence

- `npm --prefix apps/nex-ae-web test`
  - `235 passed`
- `scripts/quality/run_quality_gate.sh`
  - `3126 passed`
  - `statement_coverage=98.69%`
  - `branch_coverage=96.15%`

## Notes

- `MARK_DELETED` is still a logical lifecycle transition only. Physical storage
  mutation remains outside the AE Web browser boundary.
- The controls are wired on the selected artifact summary first; library-row
  lifecycle actions can be added later if the product flow needs bulk or
  inline management.
