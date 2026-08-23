# Slice 0318: AE Chat Grounded Response Citation-Quality Contract Wiring

## Scope

Expose CX grounded response citation-quality summary metadata through the AE
chat interaction contract.

This slice does not change database schema, provider configuration, or
PostgreSQL smoke behavior. It maps already-redacted CX generation metadata into
AE chat records, so no test DB connection is required for this slice.

## Implemented

- Added `ae_chat_grounded_response_quality.v1` as a redacted nested generation
  contract.
- Mapped CX `request_metadata.grounded_response_quality_*` fields into AE chat
  interaction records.
- Preserved raw-output, evidence-text, prompt-text, and provider-detail
  redaction flags as hard `false` contract values.
- Updated AE chat interaction examples and negative contract fixtures.
- Added a negative contract fixture for `raw_output_included=true`.

## Runtime Behavior

Completed AE chat interactions now include:

```json
"grounded_response_quality": {
  "contract_schema_version": "ae_chat_grounded_response_quality.v1",
  "boundary_status": "PASS",
  "citation_status": "VALIDATED",
  "recommended_action": "proceed"
}
```

Sparse or non-grounded CX records fall back to `NOT_REQUIRED`; grounded records
without a usable CX quality status fall back to `UNKNOWN` and
`proceed_with_caveat`.

## Evidence

- Targeted AE chat tests:
  `./.venv/bin/pytest tests/test_nex_ae_chat.py -q`
- Contract validation:
  `./.venv/bin/pytest tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
