# Slice 1236: OA effective authorization and session integration

## Result

- Added an effective-authorization resolver over direct membership grants and
  active tenant group-role assignments.
- Disabled groups, roles, assignments, foreign tenants, and unrelated users do
  not contribute grants.
- Existing direct role labels and scopes remain compatible while group roles
  must resolve through durable role definitions.
- Effective projections include bounded source counts and a deterministic
  revision hash without private identity or credential values.
- OA session issuance now uses the effective projection when configured;
  requested scopes must be a subset of effective scopes.
- Existing callers without a resolver retain direct membership behavior.
- The fifth-Slice Checkpoint Gate verifies the expanded OA regression surface.

## Verification

```bash
./scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_oa_authorization_resolver.py \
  --test tests/test_oa_effective_authorization_session.py \
  --coverage-target services/nex-oa/nex_oa/authorization_resolver.py \
  --coverage-target scripts/smoke/run_oa_effective_authorization_session.py \
  --smoke scripts/smoke/run_oa_effective_authorization_session.py
```

Observed result:

- Python regression: `9485 passed, 13 skipped`
- Statement coverage: `98.82%` (required `95%`)
- Branch coverage: `97.04%` (required `94%`)
- Authorization resolver: `100%` statement / `100%` branch
- Protected smoke runner: `100%` statement / `100%` branch
- Contract validation: `134` schemas, `192` examples, `162` negative
  examples, and `7` OpenAPI documents
- Effective-authorization session smoke: `6/6` checks
- Checkpoint Gate: `5/5` commands passed
