# Slice 0003 Contract Package Bootstrap

Status: Implemented.

Backlog candidate: `S1-003` Contract package bootstrap.

## Scope

Slice 0003 creates the first contract package structure from
[Common Schema + Contract Package Layout](../33_common_schema_contract_package_layout.md):

- `contracts/README.md`.
- `contracts/schemas/**` service and common schema directories.
- `contracts/openapi/**` bootstrap OpenAPI documents for shared components and
  all five backend services.
- `contracts/examples/index.json` example-to-schema validation index.
- `contracts/examples/common/contract_manifest.minimal.json`.
- `scripts/quality/validate_contracts.py`.
- `jsonschema` and `openapi-spec-validator` development dependencies.

## Validation Decision

Contract validation is part of the repository quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

The command validates:

- JSON Schema syntax under `contracts/schemas`.
- Indexed JSON examples under `contracts/examples`.
- OpenAPI descriptions under `contracts/openapi`.

## Evidence

Quality gate target:

```text
pytest with statement coverage and branch coverage
coverage threshold check
contract validation
```

## Follow-Up

Slice 0004 should add the common `problem+json` envelope and trace context
contract fixtures.
