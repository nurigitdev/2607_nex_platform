# W80-CA00F.5B: Primary Project Code Typed Business Context Propagation Closure

## Outcome

- Added optional, hash-bound `primary_project_code` admission to the existing
  `ae.business_request_context.v1` contract while retaining historical v1
  field-set replay compatibility.
- New Project-scoped Journal contexts always persist the validated Project code,
  including requests with no allocation list.
- PA transaction-preparation authority resolution consumes the typed context
  identity first. WorkIntent parameter lookup remains replay-only compatibility.
- General Chat/RAG continues to use WorkIntent v1.1 without a business context or
  Project requirement.
- No database migration, default Project, default PA, fixture, or authority
  shortcut was introduced.

## Verification

- Focused context, authority-source, and contract tests: `96 passed`.
- Contract validation: PASS, `279` schemas, `322` examples, `260` negative
  examples, and `10` OpenAPI documents.
- AE Slice Gate: PASS, `7,088 passed`, `55 skipped`, `6/6` commands; statement
  coverage `96.48%`, branch coverage `94.71%`.
- Installed live journey and Repository Full Gate evidence follows after the
  exact-head deployment boundary completes.

## Deferred Decision

A per-user default storage or memory scope may be useful, but it must be designed
separately from a governed EOS business Project. IA owns ordinary personal
conversations; PA creation requires an explicit future authority and lifecycle
decision.
