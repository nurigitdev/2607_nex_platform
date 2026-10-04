# Slice 1307: Platform CX-to-MO provider path audit

## Outcome

- Confirmed CX has HTTP clients for MO embedding, reranking, and generation
  capability routes and propagates an audience-bound service token, request ID,
  and trace context for every call.
- Confirmed CX does not reference remote provider hosts or vLLM endpoint
  variables. MO remains the only owner of provider endpoint details.
- Confirmed all three CX aliases resolve in the MO registry and MO exposes all
  three capability APIs.
- Identified a P0 timeout inversion: CX allows `5s` for each MO call while MO
  can wait `15s`, `15s`, and `60s` for embedding, reranking, and generation
  upstream calls respectively. Live calls can be cancelled by CX before MO's
  valid upstream budget expires.
- Identified two live-capable aliases that retain `mock-` names for historical
  compatibility. Neutral canonical aliases can be introduced later without
  removing the existing aliases.
- Identified that `.env.example` does not materialize the complete CX-to-MO
  base URL, signed service identity, and alias selection profile.

## Decision

The CX-to-MO alias boundary is correct and reusable. S132 must align timeout
budgets from outer callers to MO retries/upstream timeouts and materialize the
complete route configuration. S136/S137 will prove the same boundary with live
providers; S131 does not require provider connectivity.

No database or remote provider is required for this repository audit Slice.

## Verification

- Focused tests: `6 passed`.
- Slice Gate (`nex-cx`): `2,266 passed`.
- Coverage: statement `99.06%`, branch `98.15%`.
- Changed audit runner coverage: statement `100.00%`, branch `100.00%`.
- Contract validation: `156` schemas, `214` examples, `184` negative
  examples, and `7` OpenAPI documents.
- Audit summary: `3` CX-to-MO clients, `3` MO capability routes, `0` direct
  provider references in CX, and an unsafe `5s` versus `15/15/60s` timeout
  budget relationship.
