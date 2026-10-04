# Slice 1302: Platform vertical-spine re-audit boundary

## Outcome

- Froze S131 through S140 in
  `docs/37_platform_mvp_integration_release_plan.md` so later implementation
  cannot silently drift from the agreed platform integration goals.
- Established S131 as a repository-grounded audit of OA -> AE Web/API -> CX ->
  MO -> AG rather than a new feature requirement.
- Confirmed five backend entry points, the AE Web shell, the current local
  service runner, SRS vertical acceptance, and ten golden scenario contracts.
- Recorded the initial integration gap: the contracts name ten
  `GEN-E2E-*` scenarios, while no executable test or smoke currently carries
  those scenario IDs.
- Froze protected evidence timing: S131 needs no remote model provider;
  PostgreSQL and live providers become mandatory only in the later requirements
  named by the integration plan.

## Structural Refactoring

Historical S130 closure evidence previously required its command to remain the
last command in the Full Gate forever. The closure now requires exactly one
quality-gate registration instead. This preserves S130 evidence while allowing
S131 and later closure commands to follow it.

## Verification

The Slice Gate covers the platform boundary runner and its failure branches.
The runner must report five backend services plus the web shell, zero executable
named golden scenarios, no database/live-provider requirement for this Slice,
and the S132 handoff.

Observed evidence:

- Focused regression: `12 passed`, `1` protected test skipped.
- The initial `nex-runtime` profile was rejected at statement `91.85%` and
  branch `87.35%` because that profile includes dormant shared policy modules
  outside this Slice. No threshold exception was taken.
- The corrected integration-owner Slice Gate used the OA trust profile plus
  explicit coverage for both changed audit runners: `946 passed`, `12`
  protected tests skipped.
- Aggregate coverage: statement `98.44%`, branch `97.74%`.
- Changed-runner coverage: statement `100.00%`, branch `100.00%` for each.
- Contract validation: `156` schemas, `214` positive examples, `184` negative
  examples, and `7` OpenAPI documents.
- Boundary evidence: backend services `5` plus AE Web, executable named golden
  scenarios `0/10`, PostgreSQL not required, and live providers not required.
