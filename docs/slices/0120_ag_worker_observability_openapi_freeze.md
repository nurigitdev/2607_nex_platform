# Slice 0120: AG Worker Observability OpenAPI Freeze

## Scope

Slice 0120 closes the worker observability sequence by aligning AG OpenAPI
documentation with the worker runtime and worker detail APIs.

The AG OpenAPI contract now documents:

```text
GET /admin/v1/operations/workers
GET /admin/v1/operations/workers/{service_id}/{worker_id}
```

The shared `AgOperationsProjection` OpenAPI enum also includes:

```text
ag_worker_runtime_projection.v1
ag_worker_detail_projection.v1
```

## Regression Guard

`tests/test_contract_validation.py` now asserts that the worker detail path,
parameters, operation id, and projection schema enum are present in
`contracts/openapi/nex-ag.openapi.yaml`.

This keeps the OpenAPI surface from drifting behind the runtime routes and JSON
Schema examples added in S12.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py
./.venv/bin/python scripts/quality/validate_contracts.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
