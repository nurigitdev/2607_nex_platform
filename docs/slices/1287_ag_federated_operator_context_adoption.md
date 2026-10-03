# Slice 1287: AG federated operator-context adoption

## Outcome

- OA now projects a bounded operator context from the authoritative session
  result using only tenant, subject, roles, scopes, authentication method, and
  a domain-separated SHA-256 session digest.
- AG strictly adopts that context into request state and exposes a minimal
  user operator reference without accepting provider data, external subject,
  raw session ID, ID token, or arbitrary additional fields.
- The context transport does not introduce `delegated_user_access` JWTs. AG
  still does not validate external IdP tokens or read OA persistence.
- Caller authentication, AE caller binding, admin-role enforcement, and
  privacy-safe authorization audit are intentionally grouped in Slice 1288.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --test tests/test_ag_federated_operator_context.py \
  --coverage-target services/nex-ag/nex_ag/federated_operator_context.py \
  --coverage-target scripts/smoke/run_ag_federated_operator_context.py \
  --smoke scripts/smoke/run_ag_federated_operator_context.py
```
