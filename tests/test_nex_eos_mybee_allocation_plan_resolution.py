from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_nex_eos_mybee_allocation_plan as base
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from nex_eos import (
    ALLOCATION_PLAN_RESOLUTION_SCHEMA,
    ALLOCATION_PLAN_RESOLVE_OPERATION,
    ALLOCATION_PLAN_RESOLVE_REQUEST_SCHEMA,
    EOS_COST_ALLOCATION_PLAN_LINE_TABLE,
    EOS_COST_ALLOCATION_PLAN_TABLE,
    EosAllocationPlanError,
)
from nex_eos.allocation_plan_api import register_allocation_plan_routes
from sqlalchemy import func, select, update


def _selector() -> dict[str, object]:
    return {
        "schema_version": ALLOCATION_PLAN_RESOLVE_REQUEST_SCHEMA,
        "source_kind": "SHARED_EXPENSE",
        "scope_type": "PROJECT_SET",
        "effective_on": "2026-11-15",
        "projects": [
            {
                "project_id": base.PROJECT_B,
                "project_code": "VO00D260002",
                "allocation_ratio": "0.400000000000",
            },
            {
                "project_id": base.PROJECT_A,
                "project_code": "VO00D260001",
                "allocation_ratio": "0.600000000000",
            },
        ],
    }


def _release_default(sessions, service) -> dict[str, object]:
    payload = base._payload()
    base._seed_proof(sessions, payload)
    return service.release(
        tenant_id=base.TENANT,
        company_id=base.COMPANY_ID,
        payload=payload,
    )


def _counts(sessions) -> tuple[int, int]:
    with sessions() as session:
        return (
            session.scalar(
                select(func.count()).select_from(EOS_COST_ALLOCATION_PLAN_TABLE)
            ),
            session.scalar(
                select(func.count()).select_from(EOS_COST_ALLOCATION_PLAN_LINE_TABLE)
            ),
        )


def test_exact_resolution_is_deterministic_read_only_and_schema_valid() -> None:
    engine, sessions, auth, service = base._runtime()
    released = _release_default(sessions, service)
    auth.calls.clear()
    before = _counts(sessions)

    first = service.resolve(
        tenant_id=base.TENANT,
        company_id=base.COMPANY_ID,
        payload=_selector(),
    )
    second = service.resolve(
        tenant_id=base.TENANT,
        company_id=base.COMPANY_ID,
        payload=_selector(),
    )

    assert first == second
    assert first["schema_version"] == ALLOCATION_PLAN_RESOLUTION_SCHEMA
    assert first["operation"] == ALLOCATION_PLAN_RESOLVE_OPERATION
    assert first["resolution_disposition"] == "EXACT_MATCH"
    assert first["plan_id"] == released["plan_id"]
    assert first["plan_hash"] == released["plan_hash"]
    assert first["selector_hash"].startswith("sha256:")
    assert first["resolution_hash"].startswith("sha256:")
    assert [line["project_code"] for line in first["lines"]] == [
        "VO00D260001",
        "VO00D260002",
    ]
    assert _counts(sessions) == before
    assert auth.calls == []

    schema = json.loads(
        Path(
            "contracts/schemas/service/nex_eos/"
            "cost_allocation_plan_resolution.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(first)
    engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(source_kind="PAYROLL"),
        lambda value: value.update(effective_on="2026-12-01"),
        lambda value: (
            value["projects"][0].update(allocation_ratio="0.300000000000")
            or value["projects"][1].update(allocation_ratio="0.700000000000")
        ),
        lambda value: value["projects"][0].update(project_id=str(uuid.uuid4())),
    ],
)
def test_resolution_never_falls_back_to_nearest_plan(mutation) -> None:
    engine, sessions, _auth, service = base._runtime()
    _release_default(sessions, service)
    selector = _selector()
    mutation(selector)

    with pytest.raises(EosAllocationPlanError) as error:
        service.resolve(
            tenant_id=base.TENANT,
            company_id=base.COMPANY_ID,
            payload=selector,
        )

    assert error.value.error_code == "EOS_COST_ALLOCATION_PLAN_NOT_RESOLVED"
    assert error.value.status_code == 404
    engine.dispose()


def test_non_approved_plan_is_not_resolvable() -> None:
    engine, sessions, _auth, service = base._runtime()
    _release_default(sessions, service)
    with sessions.begin() as session:
        session.execute(
            update(EOS_COST_ALLOCATION_PLAN_TABLE).values(state="SUPERSEDED")
        )

    with pytest.raises(EosAllocationPlanError) as error:
        service.resolve(
            tenant_id=base.TENANT,
            company_id=base.COMPANY_ID,
            payload=_selector(),
        )
    assert error.value.error_code == "EOS_COST_ALLOCATION_PLAN_NOT_RESOLVED"
    engine.dispose()


def test_multiple_exact_approved_plans_are_ambiguous() -> None:
    engine, sessions, _auth, service = base._runtime()
    _release_default(sessions, service)

    proof_id = str(uuid.uuid4())
    second = base._payload(proof_id=proof_id)
    second["plan"]["plan_id"] = str(uuid.uuid4())
    base._seed_proof(sessions, second, proof_id=proof_id, suffix=20)
    service.release(
        tenant_id=base.TENANT,
        company_id=base.COMPANY_ID,
        payload=second,
    )

    with pytest.raises(EosAllocationPlanError) as error:
        service.resolve(
            tenant_id=base.TENANT,
            company_id=base.COMPANY_ID,
            payload=_selector(),
        )
    assert error.value.error_code == "EOS_COST_ALLOCATION_PLAN_AMBIGUOUS"
    assert error.value.status_code == 409
    engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version="unsupported"),
        lambda value: value.update(scope_type="PROJECT"),
        lambda value: value.update(extra="not-canonical"),
        lambda value: value.update(effective_on="not-a-date"),
        lambda value: value.update(projects=[]),
        lambda value: value["projects"][0].update(allocation_ratio="0.40000000000"),
        lambda value: value["projects"][1].update(
            project_id=value["projects"][0]["project_id"]
        ),
    ],
)
def test_resolution_selector_is_strictly_admitted(mutation) -> None:
    engine, _sessions, _auth, service = base._runtime()
    selector = _selector()
    mutation(selector)
    with pytest.raises(EosAllocationPlanError) as error:
        service.resolve(
            tenant_id=base.TENANT,
            company_id=base.COMPANY_ID,
            payload=selector,
        )
    assert error.value.error_code == "EOS_COST_ALLOCATION_PLAN_SELECTOR_INVALID"
    assert error.value.status_code == 400
    engine.dispose()


def test_resolver_contract_and_openapi_are_canonical() -> None:
    request_schema = json.loads(
        Path(
            "contracts/schemas/service/nex_eos/"
            "cost_allocation_plan_resolve.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(request_schema)
    Draft202012Validator(request_schema, format_checker=FormatChecker()).validate(
        _selector()
    )

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    route = spec["paths"]["/internal/v2/finance/cost-allocation-plans:resolve"]["post"]
    assert route["operationId"] == ALLOCATION_PLAN_RESOLVE_OPERATION
    assert route["x-nex-side-effect-free"] is True
    assert route["x-nex-business-scope"] == "finance:cost-allocation:read"
    assert set(route["responses"]) >= {"200", "400", "401", "404", "409", "503"}
    assert spec["components"]["schemas"]["CostAllocationPlanResolve"][
        "x-nex-canonical-json-schema"
    ].endswith("cost_allocation_plan_resolve.v1.schema.json")


def test_resolution_api_is_protected_no_store_and_maps_domain_errors(
    monkeypatch,
) -> None:
    engine, sessions, _auth, service = base._runtime()
    _release_default(sessions, service)
    monkeypatch.setattr(
        "nex_eos.allocation_plan_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api", audience="nex-eos", scopes=("service:call",)
        ),
    )
    app = FastAPI()
    register_allocation_plan_routes(app)
    headers = {
        "Authorization": "Bearer signed-service-token",
        "X-NeX-Tenant-Id": base.TENANT,
        "X-NeX-Company-Id": base.COMPANY_ID,
    }
    with TestClient(app) as client:
        unavailable = client.post(
            "/internal/v2/finance/cost-allocation-plans:resolve",
            headers=headers,
            json=_selector(),
        )
        app.state.eos_allocation_plan_service = service
        resolved = client.post(
            "/internal/v2/finance/cost-allocation-plans:resolve",
            headers=headers,
            json=_selector(),
        )
        missing_selector = _selector()
        missing_selector["source_kind"] = "PAYROLL"
        missing = client.post(
            "/internal/v2/finance/cost-allocation-plans:resolve",
            headers=headers,
            json=missing_selector,
        )

    assert unavailable.status_code == 503
    assert resolved.status_code == 200
    assert missing.status_code == 404
    for response in (unavailable, resolved, missing):
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["pragma"] == "no-cache"
    engine.dispose()


def test_resolution_api_token_denial_is_no_store(monkeypatch) -> None:
    app = FastAPI()
    register_allocation_plan_routes(app)
    monkeypatch.setattr(
        "nex_eos.allocation_plan_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: JSONResponse(
            {"error_code": "TOKEN_DENIED"}, status_code=401
        ),
    )
    with TestClient(app) as client:
        response = client.post(
            "/internal/v2/finance/cost-allocation-plans:resolve",
            headers={
                "Authorization": "Bearer invalid",
                "X-NeX-Tenant-Id": base.TENANT,
                "X-NeX-Company-Id": base.COMPANY_ID,
            },
            json=_selector(),
        )
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store, max-age=0"


def test_resolution_api_maps_non_object_selector_to_domain_400(monkeypatch) -> None:
    engine, _sessions, _auth, service = base._runtime()
    monkeypatch.setattr(
        "nex_eos.allocation_plan_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api", audience="nex-eos", scopes=("service:call",)
        ),
    )
    app = FastAPI()
    app.state.eos_allocation_plan_service = service
    register_allocation_plan_routes(app)
    with TestClient(app) as client:
        response = client.post(
            "/internal/v2/finance/cost-allocation-plans:resolve",
            headers={
                "Authorization": "Bearer signed-service-token",
                "X-NeX-Tenant-Id": base.TENANT,
                "X-NeX-Company-Id": base.COMPANY_ID,
            },
            json=[],
        )
    assert response.status_code == 400
    assert response.json()["error_code"] == (
        "EOS_COST_ALLOCATION_PLAN_SELECTOR_INVALID"
    )
    assert response.headers["cache-control"] == "no-store, max-age=0"
    engine.dispose()
