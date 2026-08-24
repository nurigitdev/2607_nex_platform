# Slice 0323: AG Generation Audit Quality Contract Schema Hardening

## Scope

Harden the AG grounded response quality projection contract introduced in Slice
0322.

This slice does not change database schema, provider configuration, route
behavior, or PostgreSQL smoke behavior. It adds JSON Schema validation coverage
for the compact AG generation audit quality projection.

## Implemented

- Added
  `ag_generation_audit_grounded_response_quality_projection.v1.schema.json`.
- Added a positive contract fixture for a passing grounded response quality
  projection.
- Added a negative fixture that rejects raw generated output leakage.
- Registered the new positive and negative fixtures in contract indexes.
- Added AG regression coverage that validates the runtime projection against the
  new schema.
- Locked redaction flags to `false` for raw content, prompt text, evidence text,
  and provider detail exposure.

## Runtime Behavior

The AG runtime projection remains the same as Slice 0322. The new schema now
guards its public shape:

```text
projection_schema_version=ag_generation_audit_grounded_response_quality_projection.v1
gap_audit_schema_version=ag_generation_audit_grounded_response_quality_gap_audit.v1
```

The contract accepts safe status/count/hash/id metadata and rejects raw output
or unexpected fields.

Recommended next slice:

```text
Slice 0324: AG generation audit quality dashboard surface
```

## Evidence

- Targeted AG regression:
  `./.venv/bin/pytest tests/test_nex_ag_generation_audit.py -q`
- Contract validation:
  `./.venv/bin/pytest tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted AG result:

```text
19 passed, 1 warning
```

Observed targeted contract result:

```text
21 passed
```

Observed full quality gate:

```text
2196 passed, 1 warning
statement_coverage=98.53% threshold=95.00%
branch_coverage=95.42% threshold=85.00%
contract_validation=pass schemas=51 examples=83 negative_examples=60 openapi=7
```
