# Slice 1219: OA identity lifecycle contract, audit, and privacy hardening

## Goal

Publish strict subject and membership lifecycle wire contracts, document the two
protected runtime routes, and rebaseline OA lifecycle audits to the implemented
revision and session-revocation controls.

## Behavior

- Subject and membership lifecycle responses have separate Draft 2020-12 JSON
  Schemas with strict fields, entity-specific states, event lineage, and
  session-revocation counts.
- Positive fixtures cover canonical disabled transitions. Negative fixtures
  prove password, password-hash, and access-token fields are rejected.
- Both lifecycle PATCH operations require the service bearer claim plus
  `service:call` and `identity:lifecycle:write` scopes in OpenAPI.
- The S121 lifecycle audit now recognizes direct lifecycle transitions and the
  atomic deprovision cascade as implemented. Group lifecycle and dedicated
  bootstrap authorization remain explicit deferred gaps.
- The historical S121 closure accepts improvements below its captured gap and
  drift ceilings instead of treating hardening as regression.

No PostgreSQL or remote provider access is required in this slice. Actual
`nex_oa_test` migration and lifecycle evidence is reserved for Slice 1220.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_identity_lifecycle_contracts.py \
  --test tests/test_oa_identity_lifecycle_audit.py \
  --test tests/test_oa_contract_api_drift_audit.py \
  --test tests/test_s121_oa_current_state_reaudit_closure.py \
  --coverage-target scripts/smoke/run_oa_identity_lifecycle_contracts.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle_audit.py \
  --smoke scripts/smoke/run_oa_identity_lifecycle_contracts.py
```
