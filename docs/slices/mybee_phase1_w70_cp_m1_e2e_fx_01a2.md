# CP-M1-E2E-FX-01A.2: Trusted Project Delegation Planning

## Status

- Slice: `CP-M1-E2E-FX-01A.2`
- Status: `CLOSED`
- Database migration: none
- Remote provider: not required

## Decision

The public IA path remains Project-neutral. An LLM-emitted Project Code is an
untrusted selector until all three current authorities agree:

1. EOS resolves exactly one active Project Code;
2. OA returns a fresh allowed Project decision for the requester; and
3. AE resolves exactly one active synchronized PA projection for that Project.

Only then is the stable EOS Project UUID admitted as a trusted resolved entity
and as the `DELEGATE_WORK.project_scope_ref`. The IA `AgentContext.project_ref`
remains null, preserving the P4 project-neutral IA contract.

## Implementation

- Added a versioned M1 Project delegation intent activator and fail-closed
  EOS/OA/AE authority sources.
- Added a capability-keyed PLAN profile registry instead of a scenario branch.
- Added a separate `p7.plan_candidate.v1` prompt binding for Project
  delegation; the default P6.5 PLAN profile remains unchanged.
- Promoted the active intent prompt to v8 and retained v7 as replay history.
- Allowed `DELEGATE_WORK` validation to consume one trusted Project entity from
  an IA context without assigning the Project as IA ownership scope.
- Preserved the Golden A selection freeze and made no NSL/compiler/runtime or
  database-schema change.

## Negative Matrix

- absent or multiple Project Codes: blocked
- EOS missing/inactive/malformed Project: blocked
- OA denied, stale, or malformed decision: blocked
- absent, duplicate, inactive, suspended, or non-ordinary PA: blocked
- model-invented Project UUID or mismatched delegation scope: blocked
- incomplete EOS/OA service configuration: startup admission blocked

## Verification

- focused Project delegation/profile/prompt tests: `153 passed`
- first AE Slice Gate: correctly detected two prompt-persistence baseline
  mismatches; historical v1 ordering and the new binding inventory were fixed
- final AE Slice Gate: PASS (recorded in the tiered quality report)
- next boundary: `CP-M1-E2E-FX-01A.3`
