# Slice 1239: OA authorization contract and privacy hardening

## Result

- Added six strict canonical JSON Schemas for role, group, assignment,
  mutation response, effective authorization, and authorization-event list
  payloads.
- Added six valid fixtures and six negative fixtures covering private metadata,
  path-identity override, token, password, and cookie leakage.
- Linked all six authorization operations to canonical OpenAPI request/response
  components with `service:call` plus admin/read scopes.
- Documented the subject and membership compatibility bootstrap operations with
  `identity:bootstrap:write`.
- Validated four runtime mutation response variants plus effective and event
  reads against canonical schemas.
- OA runtime/OpenAPI drift decreased from `23` to `21`; historical closure
  guards accept improvement but still fail if drift rises above their baseline.
- No database table or migration changed in this Slice.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_authorization_contracts.py \
  --test tests/test_oa_contract_api_drift_audit.py \
  --test tests/test_oa_credential_security_contracts.py \
  --test tests/test_oa_identity_lifecycle_contracts.py \
  --coverage-target scripts/smoke/run_oa_authorization_contracts.py \
  --smoke scripts/smoke/run_oa_authorization_contracts.py
```

Observed result:

- OA regression: `388 passed, 2 skipped`
- Statement coverage: `98.59%` (required `95%`)
- Branch coverage: `96.81%` (required `94%`)
- Authorization contract runner: `100%` statement / `100%` branch
- Contract validation: `140` schemas, `198` examples, `168` negative
  examples, and `7` OpenAPI documents
- Authorization contracts: `6/6` positive, `6/6` negative, `8/8`
  operations, and `6/6` runtime responses
- Slice Gate: `5/5` commands passed
