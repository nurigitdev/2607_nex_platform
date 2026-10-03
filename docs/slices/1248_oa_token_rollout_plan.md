# Slice 1248: OA cross-service token migration and rollout plan

## Goal

Define an ordered, observable migration from explicit test mock tokens to
signed-only production trust without silent fallback or trust-broadening
rollback.

## Decision

- Profiles advance one way: `TEST_MOCK -> DUAL_READ -> SIGNED_ONLY`.
  `TEST_MOCK` is restricted to explicit non-production test environments.
- `DUAL_READ` issues only signed tokens. It accepts mock tokens solely for a
  named legacy-caller allowlist with a fixed removal deadline. It never uses
  `configured token or mock token` fallback.
- `SIGNED_ONLY` requires mock acceptance disabled and zero observed legacy
  calls. A failed rollout stops forward progress; automatic rollback to a
  broader trust profile is forbidden.
- Rollout order is shared verifier/OA issuer, AE, CX, MO, then AG. A unit
  cannot advance until every predecessor is complete.
- Signed stages require JWKS and introspection readiness, provisioned service
  principal, signed outbound token support, reviewed audience/scope mapping,
  negative authorization tests, redacted telemetry, and disabled mock
  fallback.
- This Slice changes no runtime profile. S126 implements the controls and
  records migration evidence per unit.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_token_rollout_policy.py \
  --test tests/test_oa_token_rollout_plan.py \
  --coverage-target services/nex-oa/nex_oa/token_rollout_policy.py \
  --coverage-target scripts/smoke/run_oa_token_rollout_plan.py \
  --smoke scripts/smoke/run_oa_token_rollout_plan.py
```
