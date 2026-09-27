# Slice 1026: AE Runtime Policy Inspection API

## Goal

Expose protected, privacy-safe runtime-policy catalog, resolution, and prompt
binding inspection APIs backed by the same production prompt registry.

## Implementation

- Add service-token and browser-session protected runtime-policy routes.
- Resolve an exact runtime policy and verify its active prompt binding/version.
- Return prompt IDs, version, role, capability, and content hash without prompt
  content, user prompt text, or provider runtime configuration.
- Build and seed the AE prompt registry from the service persistence session
  factory while retaining deterministic in-memory fallback for tests.
- Reuse one prompt store for legacy prompt routes and S103 policy routes.

## Decisions

- Policy inspection is read-only; prompt modification remains outside this API.
- Missing or inactive bindings and version mismatches fail closed.
- PostgreSQL and remote providers are not required until Slice 1030.

## Verification

```bash
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_ae_runtime_policy_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/runtime_policy_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/prompts.py \
  --smoke scripts/smoke/run_ae_runtime_policy_api.py
```

## Observed Evidence

- Checkpoint Gate: `7,647 passed` with known dependency warnings.
- Repository statement coverage: `98.65%`.
- Repository branch coverage: `96.58%`.
- Runtime-policy API and prompt builder statement/branch coverage:
  `100%`/`100%` each.
- Contract validation: `93` schemas, `147` examples, `110` negative
  examples, and `7` OpenAPI documents.
- Runtime-policy API smoke: `11/11`, next Slice `1027`.
