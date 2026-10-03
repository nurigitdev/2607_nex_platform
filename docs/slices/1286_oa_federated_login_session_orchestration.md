# Slice 1286: OA federated login and session orchestration

## Outcome

- Added federated login orchestration from verified OIDC identity, through an
  exact persisted subject-digest link, into the existing OA session issuer.
- Added a bounded HTTP discovery/JWKS document adapter with no redirects,
  five-second timeout, 64 KiB response limit, mapping-only JSON, and redacted
  failure handling.
- Added provider-revision-aware verifier reuse so trust changes replace stale
  caches without retaining old provider revisions.
- Added a protected route foundation for AE-to-OA federated login calls and
  privacy-safe success/failure auth events.
- The response carries the same opaque OA session shape as password login plus
  a safe `federated_oidc` marker. ID token, nonce, external subject, and IdP
  profile values are not returned or audited.

This Slice completes the fifth-Slice S129 Checkpoint Gate. Runtime registration
and canonical OpenAPI publication remain grouped with Slice 1289 contract
hardening so runtime/contract parity moves atomically.

## Verification

```bash
./scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_oa_federated_login.py \
  --coverage-target services/nex-oa/nex_oa/federated_login.py \
  --coverage-target scripts/smoke/run_oa_federated_login_orchestration.py \
  --smoke scripts/smoke/run_oa_federated_login_orchestration.py
```
