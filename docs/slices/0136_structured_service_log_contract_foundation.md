# Slice 0136: Structured Service Log Contract Foundation

## Scope

Slice 0136 introduces the shared structured service log entry contract and
runtime helpers. This is the contract-first base for later service-local log
persistence and AG log search.

Implemented:

- `contracts/schemas/common/service_log_entry.v1.schema.json`
- positive and negative contract fixtures for service log entries
- `nex_runtime.service_logs` builder, validator, attribute redaction, and
  summary helpers
- shared runtime exports from `nex_runtime`

## Contract Shape

`service_log_entry.v1` captures diagnostic log lines with:

- service id and severity
- logger name and bounded message
- trace/request/job/subject correlation fields
- redaction-safe structured attributes
- explicit `redacted_attribute_keys`
- observed timestamp

The contract rejects sensitive top-level attribute keys such as `api_key`,
`authorization`, `password`, `raw_prompt`, `source_text`, and `token`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_service_logs.py tests/test_contract_validation.py
./.venv/bin/python scripts/quality/validate_contracts.py
```
