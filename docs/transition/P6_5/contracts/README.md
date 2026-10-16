# P6.5 Semantic Candidate Contracts

This directory contains the P6.5-CA01 machine-readable transition contracts.

Model-generated payload contracts:

- `p65-intent-candidate-v1.schema.json`
- `p65-context-candidate-set-v1.schema.json`
- `p65-plan-candidate-v1.schema.json`

Platform-authored evidence envelope:

- `p65-semantic-candidate-evidence-v1.schema.json`

The payload contracts intentionally exclude tenant, principal, execution,
candidate identity, exact capability version, trust, provider credentials,
hashes, and provenance. AE owns those fields and records them in the evidence
envelope after deterministic validation.

`examples/` contains coherent Golden payloads and one admitted evidence
record. `tests/negative/` contains authority, delegation, and secret-leak
fixtures that must fail their paired schemas.
