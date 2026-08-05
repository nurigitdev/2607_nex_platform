# Slice 0106: AG Operations Contract Examples Freeze

## Scope

Slice 0106 freezes the current AG operations projection family as a contract
surface before adding more observability behavior.

The frozen family covers:

- operation source readiness
- operational event list/detail/search
- operational event taxonomy
- job operations list/detail/lifecycle timeline
- unified jobs plus events projection
- cross-service trace timeline

## Contract Artifacts

Schema:

```text
contracts/schemas/service/nex_ag/operations_projection.v1.schema.json
```

Positive examples:

```text
contracts/examples/operations/
```

Negative examples:

```text
contracts/tests/negative/operations/
```

The examples are registered in `contracts/examples/index.json`, and the
negative fixtures are registered in `contracts/tests/negative/index.json`.

## OpenAPI Surface

`contracts/openapi/nex-ag.openapi.yaml` now documents the AG operations routes
under the `Operations` tag:

- `GET /admin/v1/operations`
- `GET /admin/v1/operations/sources`
- `GET /admin/v1/operations/event-taxonomy`
- `GET /admin/v1/operations/events`
- `GET /admin/v1/operations/events/{event_id}`
- `GET /admin/v1/operations/jobs`
- `GET /admin/v1/operations/jobs/{service_id}/{job_id}`
- `GET /admin/v1/operations/traces/{trace_id}`

## Regression Guard

`tests/test_nex_ag_operations.py` validates the live runtime builders against
the frozen JSON Schema so future AG operations changes cannot drift silently
from the contract examples.

## Evidence

Targeted contract and AG operations regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_ag_operations.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
