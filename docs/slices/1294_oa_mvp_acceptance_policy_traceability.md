# Slice 1294: OA MVP acceptance policy and traceability

## Outcome

- Mapped OA-FR-001 through OA-FR-005 to 26 current implementation, test, and
  closure artifacts.
- All five requirements are blocking for S130 acceptance, including the
  `Should`-priority safe audit requirement.
- Browser access remains an opaque OA-backed session. Service access requires
  short-lived RS256 tokens and the `SIGNED_ONLY` runtime profile.
- Sensitive routes require local signature validation plus live OA
  introspection.
- Final acceptance requires six remaining live/closure gates: PostgreSQL
  restart, key rotation, revocation, cross-service protection,
  contract/privacy, and Full Gate evidence.
- A required gate cannot be skipped. Raw secrets, access tokens, and private
  signing-key material cannot be used as projected evidence.
- No new table or remote model provider is required.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_mvp_acceptance_policy_traceability.py \
  --coverage-target scripts/smoke/run_oa_mvp_acceptance_policy_traceability.py \
  --smoke scripts/smoke/run_oa_mvp_acceptance_policy_traceability.py
```
