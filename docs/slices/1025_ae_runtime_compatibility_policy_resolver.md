# Slice 1025: AE Runtime Compatibility Policy Resolver

## Goal

Resolve intent, template, prompt binding, output contract, artifact behavior,
generation limits, and quality policy as one exact, hash-addressed AE decision.

## Implementation

- Add six active AE policies covering general answer, grounded answer, summary,
  and report/proposal/memo document generation.
- Require exact active-rule matching and reject missing or ambiguous policy.
- Require explicit prompt/template/output versions and reject `latest` in
  resolved runtime records.
- Bound output tokens, temperature, streaming type, and timeout budget.
- Reject provider URL, port, API key, model path, and vLLM-specific fields at
  the AE boundary.
- Return a privacy-safe policy snapshot and deterministic SHA-256 hash without
  raw user prompt or provider runtime configuration.

## Decisions

- AE policy resolution is separate from the legacy shared compatibility
  endpoint until API and contract migration are proven.
- `report`, `proposal`, and `memo` use distinct exact rules even though they
  currently share one prompt binding and output schema.
- CX remains authoritative for final evidence and provider-facing compatibility
  validation.
- No database or remote provider is required for this Slice.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_runtime_policy_resolver.py \
  --coverage-target services/nex-ae-api/nex_ae_api/runtime_policy.py \
  --coverage-target scripts/smoke/run_ae_runtime_policy_resolver.py \
  --smoke scripts/smoke/run_ae_runtime_policy_resolver.py
```

## Observed Evidence

- Slice Gate: `2041 passed` with one known warning.
- Repository statement coverage: `97.86%`.
- Repository branch coverage: `95.62%`.
- Runtime policy statement/branch coverage: `100%`/`100%`.
- Resolver smoke: `9/9`, four representative rules, next Slice `1026`.
