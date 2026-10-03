# Slice 1289: S129 contract, runtime, observability, and privacy hardening

## Outcome

- Wired OA federation persistence, bounded OIDC document loading, federated
  session orchestration, and the protected login route into the OA runtime.
- Wired AG authorization telemetry and its protected operations route into the
  AG runtime. Telemetry is aggregate-only and stores no tenant, subject,
  session digest, provider, external identity, header, or token values.
- Published canonical OA federated request/response and AG operator
  context/runtime schemas with positive and privacy-negative fixtures.
- Published OA and AG OpenAPI operations, including the bounded optional AG
  context carrier. OA runtime/OpenAPI covered operations increased to 31 and
  known contract drift returned from 23 to 22.
- No `delegated_user_access` JWT or cross-service database read was introduced.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-ag \
  --test tests/test_s129_contract_runtime_privacy.py \
  --coverage-target services/nex-ag/nex_ag/federated_operator_authorization.py \
  --coverage-target services/nex-ag/nex_ag/federated_operator_operations.py \
  --coverage-target scripts/smoke/run_s129_contract_runtime_privacy.py \
  --smoke scripts/smoke/run_s129_contract_runtime_privacy.py
```
