# Slice 0891: AG MVP acceptance and CX transition boundary audit

## Goal

Start S90 by fixing the final NeX-AG service MVP acceptance boundary and the
conditions that permit implementation focus to move to NeX-CX.

## Decision

- S90 accepts the NeX-AG **service MVP**. It is not product-wide release
  approval or production deployment certification.
- Acceptance evidence is derived from repository state, executable closure
  checks, strict contract validation, full regression and coverage results,
  and protected smoke execution against the actual `nex_ag_test` database.
- Every blocking gate must pass before the CX transition is marked ready.
  Missing, stale, skipped-when-required, or unverifiable evidence blocks the
  transition.
- S90 adds no business table and does not mutate AG operational records merely
  to manufacture acceptance evidence.
- NeX-AG remains owner of its runtime and operational records. The transition
  package gives NeX-CX safe contracts, dependencies, deferred risks, and the
  next implementation entry point; it does not move AG data into CX.
- Production rollout, production identity and external notification
  integrations, distributed load certification, and disaster-recovery
  certification remain explicit deferred scope.

## Blocking Gate Families

1. S63-S89 AG requirement closure evidence and prerequisite AG foundations.
2. Strict JSON Schema and OpenAPI contract validation.
3. Unit and aggregate regression tests.
4. Statement and branch coverage thresholds.
5. Protected smoke evidence against the actual `nex_ag_test` PostgreSQL DB.
6. Privacy, failure-mode, and operator runbook evidence.
7. A complete, redacted NeX-CX transition handoff package.

## Slice Plan

- Slice 0891: boundary audit and refactoring checkpoint.
- Slice 0892: acceptance policy and gate-severity contract.
- Slice 0893: canonical AG evidence inventory and freshness rules.
- Slice 0894: deterministic acceptance evaluator.
- Slice 0895: protected acceptance API.
- Slice 0896: contract and operations projection hardening.
- Slice 0897: redacted CX transition handoff package.
- Slice 0898: actual `nex_ag_test` PostgreSQL acceptance smoke.
- Slice 0899: privacy, failure-mode, and transition runbook evidence.
- Slice 0900: S90 closure checkpoint.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_mvp_acceptance_cx_transition_boundary_audit.py \
  --summary

./.venv/bin/pytest -q \
  tests/test_ag_mvp_acceptance_cx_transition_boundary_audit.py \
  --cov=run_ag_mvp_acceptance_cx_transition_boundary_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
boundary audit: PASS, scope=nex_ag_service_mvp, target=nex-cx
focused tests: 5 passed, runner statement/branch coverage 100%
aggregate regression: 6164 passed, 1 known warning
statement=74857/75738=98.836779423803%
branch=17486/18136=96.415968239965%
```
