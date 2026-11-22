# CP-M1-E2E-FX-01A.1: Installed Runtime Entry Baseline

## Status

- Slice: `CP-M1-E2E-FX-01A.1`
- Status: `CLOSED`
- Database migration: none
- Remote provider: not required

## Decision

This checkpoint freezes the source-backed pre-change state for the installed
PA delegation and multi-Skill runtime correction. The immutable baseline is
stored at
`deployment/audits/mybee-w70-e2e-fx-01a1-baseline.v1.json`.

The baseline records eight installed composition owners, ten authoritative
data origins, the current Golden/Demo residue, and the exact source hashes at
entry. It is historical evidence and is not regenerated after `.2` begins.

## Findings

1. WC claim handoff stops after durable `AgentExecution` admission.
2. `BackgroundAgentPlanningService` exists but is not composed into the
   installed handoff route.
3. The installed worker is generic, while its product executor profile still
   admits one Golden A Skill root.
4. The signed D04/D12 release and mixed registry are valid checkpoint assets,
   but they are not selected by canonical OCI/Compose.
5. Product consumer and activator construction remain fixed to Golden A.
6. No new authoritative entity or database migration is necessary.

## Data-Origin Boundary

Tenant/requester comes from OA-backed authentication; Project Code and state
come from EOS with fresh OA entitlement; Project Agent comes from AE's
synchronized projection; delegation/claim comes from WC; execution/plan/job
state comes from AE; exact capability and Skill come from the immutable
registry and signed release. Model text, fixture values, filenames, directory
order, and smoke-runner state mutation are prohibited substitutes.

## Verification

- immutable baseline builder/check: PASS
- malformed/hash/incomplete baseline negatives: PASS
- source/refactoring checkpoint: PASS
- next boundary: `CP-M1-E2E-FX-01A.2`
