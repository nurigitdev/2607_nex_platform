# Slice 1313: Platform runtime manifest domain

## Outcome

- Added immutable runtime manifest types for modes, endpoints, probes, and
  processes.
- Added structural validation for schema/profile values, timeout bounds,
  endpoint URLs, process identity, commands, network bindings, probes,
  environment names, and dependencies.
- Added a public projection that exposes topology and mode metadata without
  process commands or environment values.
- Kept profile-specific protected validation in Slice 1314.

## Verification

- Focused regression: `16 passed`.
- Slice Gate: `950 passed`, `11 skipped`.
- Aggregate coverage: `98.45%` statement, `97.80%` branch.
- Changed manifest and evidence modules: `100.00%` statement and branch.
- Contract validation: `156` schemas, `214` positive examples, `184`
  negative examples, and `7` OpenAPI documents.
- Standalone smoke: `profile=local_mock`, one endpoint, one process, next
  Slice `1314`.
