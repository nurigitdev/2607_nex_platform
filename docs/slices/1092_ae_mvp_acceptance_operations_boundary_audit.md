# Slice 1092: AE MVP Acceptance and Operations Boundary Audit

## Goal

Freeze the NeX-AE service MVP acceptance and operations boundary before adding
acceptance policy, evidence evaluation, or operator-facing projections.

## Decision

- S110 accepts the combined `nex-ae-api` and `nex-ae-web` service MVP. It is
  not product-wide release approval or production deployment certification.
- S101 through S109 closure evidence, contracts, regression and coverage,
  actual `nex_ae_test` and `nex_cx_test` execution, Playwright, live providers,
  privacy runbooks, and an operations handoff are blocking evidence families.
- Required evidence is server-derived, fresh, privacy-safe, and fail-closed.
  Missing, stale, malformed, or skipped required evidence blocks acceptance.
- The acceptance read model never contains raw prompts, source text, generated
  content, storage paths, provider endpoints, credentials, or database URLs.
- No business table or migration is introduced. S110 evaluates and packages
  existing evidence without manufacturing acceptance records.
- Production identity-provider activation, object storage, distributed load,
  and disaster-recovery certification remain explicit advisory deferrals.

## Slice Plan

1. Slice 1092: boundary audit and refactoring checkpoint.
2. Slice 1093: acceptance policy and blocking gates.
3. Slice 1094: S101-S109 evidence inventory and freshness.
4. Slice 1095: deterministic fail-closed evaluator.
5. Slice 1096: protected read-only operations API.
6. Slice 1097: contract and OpenAPI hardening.
7. Slice 1098: redacted operations handoff package.
8. Slice 1099: actual PostgreSQL, DGX, and Playwright acceptance smoke.
9. Slice 1100: privacy, failure, recovery, and operator runbook evidence.
10. Slice 1101: S110 closure and Full Gate.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_ae_mvp_acceptance_operations_boundary_audit.py
./.venv/bin/python \
  scripts/smoke/run_ae_mvp_acceptance_operations_boundary_audit.py --summary
```

## Result

- Nine requirement closures are present for S101 through S109.
- Eight implementation gaps are tracked for Slice 1093 through Slice 1100.
- Existing AE/CX PostgreSQL, live-provider, and Playwright evidence is reusable.
- Boundary status: `BOUNDARY_FROZEN`; next Slice: `1093`.
