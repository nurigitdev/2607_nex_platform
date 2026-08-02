# Contract Package

Status: Slice 0003 bootstrap.

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
