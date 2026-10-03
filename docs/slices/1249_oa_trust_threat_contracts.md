# Slice 1249: OA trust privacy, threat, and contract evidence

## Goal

Make the S125 threat model machine-verifiable and prove that security evidence
cannot contain raw tokens, private keys, credentials, or session handles.

## Decision

- The required threat set covers algorithm confusion, `kid` injection,
  audience confusion, replay, stale authorization, key/credential disclosure,
  JWKS or introspection outage, and raw-token logging.
- Each threat records severity, preventive controls, detection signals,
  failure behavior, and residual risk. Critical threats are algorithm
  confusion and key/credential disclosure.
- Evidence may contain only bounded operational identifiers such as service
  ID, key ID, token fingerprint, reason code, and aggregate count. Raw tokens,
  private keys, credential secrets, passwords, and opaque session handles are
  forbidden.
- A strict JSON Schema, canonical passing fixture, and raw-token negative
  fixture are registered in the global contract validator. The evidence is an
  operations contract, not a production token API, so OpenAPI remains honest
  about the current mock routes until S126.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_trust_threat_policy.py \
  --test tests/test_oa_trust_threat_contracts.py \
  --coverage-target services/nex-oa/nex_oa/trust_threat_policy.py \
  --coverage-target scripts/smoke/run_oa_trust_threat_contracts.py \
  --smoke scripts/smoke/run_oa_trust_threat_contracts.py
```
