# Slice 0145: Service Log Query and Retention Policy Contract

## Scope

Slice 0145 adds a read-only AG policy projection for structured service log
query limits, supported filters, redaction behavior, and retention boundaries.

Implemented:

- `ag_service_log_query_policy_projection.v1`
- `service_log_query_policy.v1`
- `GET /admin/v1/operations/logs/policy`
- contract schema, OpenAPI, and example coverage
- operations dashboard smoke coverage for the policy endpoint

## Policy

The active policy is `service-log-query-retention-v1`.

Query defaults:

- default limit: `50`
- maximum limit: `500`
- text query maximum: `128` characters
- default sort: `desc`
- timestamp field: `observed_at`
- cursor mode: offset string

Retention boundaries:

- default retention: `30` days
- minimum retention: `7` days
- maximum retention: `365` days
- storage owner: service-local
- purge execution: not implemented in this Slice
- future archive target: object storage or cold table

## Boundary

This Slice establishes the contract and AG visibility surface only. It does not
delete rows, create retention workers, or move service logs to object storage.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_smoke_helpers.py tests/test_contract_validation.py
```

Operations smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
```

