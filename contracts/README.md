# Contract Package

Status: Contract catalog through Slice 0011.

This directory is the canonical home for shared JSON Schemas, OpenAPI
descriptions, contract examples, and negative fixtures.

## Layout

```text
contracts/
  schemas/
    common/
    generation/
    service/
      nex_oa/
      nex_ag/
      nex_ae_api/
      nex_cx/
      nex_mo/
  openapi/
  examples/
  tests/
    fixtures/
    negative/
```

## Validation

Run the contract validation command directly:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

The repository quality gate also runs this command after regression and
coverage checks:

```bash
scripts/quality/run_quality_gate.sh
```

## Example Index Convention

`examples/index.json` maps payload examples to the schema that validates them.
Paths are relative to this directory. This keeps payload examples clean while
still making validation explicit.

## Negative Fixture Convention

`tests/negative/index.json` maps rejection fixtures to the schema that should
reject them. The validation command fails if a negative fixture becomes valid.

## Current Contract Families

- Common envelopes: contract manifest, problem+json, trace refs, service claims,
  common job.
- Generation: MO provider route, MO model profile, CX generation execution
  record, AE chat interaction.
- Retrieval/content ingestion: CX upload registration, queued ingestion job,
  mock text extraction result, chunk set, embedding index, lexical index, and
  retrieval context package.
- Audit: AG readiness projection.
