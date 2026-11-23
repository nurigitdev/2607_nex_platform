# W80-CA00E.4 Role-Scoped Planning Profile Registry

## Outcome

W80-CA00E.4 is complete. AE plan-profile selection now uses the immutable
four-part key `capability_id + planning_source_type + agent_type +
planning_purpose` instead of capability-only lookup.

## Implemented Boundary

- Upgraded plan-profile registration and registry projections to v2.
- Added the admitted purposes `INTERACTION_RESPONSE`, `DELEGATION`,
  `CLAIMED_WORK_EXECUTION`, `PRODUCT_PREPARATION`, and `RESULT_SYNTHESIS`.
- Registered IA Project routing as `IA_PROMPT + IA + DELEGATION`.
- Registered claimed PA product planning as
  `CLAIMED_WORKITEM + PA + PRODUCT_PREPARATION`.
- Registered explicit compatibility profiles for IA interaction response and
  CA/PA/EA claimed-work execution.
- Added installed semantic-admission routing so product proposal generation
  selects `PRODUCT_PREPARATION`, while ordinary claimed planning selects
  `CLAIMED_WORK_EXECUTION`.
- Kept direct compatibility/test plan services on their existing method
  contract; only the installed profile-aware wrapper receives selector fields.

## Fail-Closed Rules

- Exact profile lookup never crosses planning source, Agent role, or purpose.
- Compatibility fallback is admitted only when a compatibility registration
  exists for the same source/role/purpose scope.
- A PA claimed execution cannot select an IA delegation profile even when the
  capability ID is identical.
- Missing exact and compatibility registrations fail with
  `PLAN_PROFILE_NOT_REGISTERED`.
- Registrations contain no tenant, Project, fixed ratio, or scenario payload.

## Verification

- Profile registry statement/branch coverage: `100% / 100%`
- Focused affected regression: `137 passed`
- AE Slice Gate: `6981 passed`, `53 skipped`; statement `96.46%`, branch
  `94.71%`
- AE product coverage: statement `97.07%`, branch `95.00%`
- Contract validation: `277 schemas`, `322 examples`, `260 negative examples`,
  `10 OpenAPI`
- Ruff and `git diff --check`: pass

Machine-readable evidence:

```text
reports/quality/mybee-w80-ca00e4-ae-slice-gate.json
```

## Persistence

No database migration or public API field was added. Existing WorkIntent,
AgentContext, AgentExecution, profile source identity, and prompt binding
storage remain authoritative.

## Next Boundary

W80-CA00E.5 may harden deterministic reuse decisions, full-pipeline fallback,
exact replay, restart, and ACK-loss recovery. Durable replay must not duplicate
provider calls after admitted semantic evidence exists.
