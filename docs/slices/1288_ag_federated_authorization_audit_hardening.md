# Slice 1288: AG federated authorization and audit hardening

## Outcome

- Added a bounded base64url JSON carrier for the six-field OA-normalized
  federated operator context. Unknown, oversized, malformed, and private
  identity fields fail closed.
- AG accepts that context only beside an admitted `nex-ae-api` service token.
  The protected path requires both `workspace:use` and the effective `admin`
  role; a context-bearing call uses the `ADMIN` service-token route class.
- Existing service automation and direct mock-admin compatibility remain
  unchanged when no federated context header is present.
- Authorization decisions retain only safe caller, tenant, subject, auth
  method, and session-digest evidence. Raw headers, service tokens, external
  IdP claims, and provider identifiers are not retained.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-ag \
  --test tests/test_ag_federated_operator_authorization.py \
  --coverage-target services/nex-ag/nex_ag/federated_operator_authorization.py \
  --coverage-target services/nex-ag/nex_ag/federated_operator_context.py \
  --smoke scripts/smoke/run_ag_federated_authorization_hardening.py
```
