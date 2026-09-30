from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import httpx
from jsonschema import Draft202012Validator, ValidationError
import pytest
import yaml

import nex_mo.provider_auth as provider_auth
from nex_mo.main import PROVIDER_READINESS, app
from nex_mo.provider_readiness_api import register_provider_readiness_routes
from nex_mo.provider_readiness_service import ProviderReadinessService
from nex_runtime import issue_mock_service_token
import run_mo_provider_route_health_api as runner


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "contracts/schemas/service/nex_mo/provider_readiness.v1.schema.json"
)
EXAMPLE_PATH = (
    ROOT / "contracts/examples/provider/mo_provider_readiness.mock_ready.json"
)
NEGATIVE_PATH = (
    ROOT
    / "contracts/tests/negative/provider/mo_provider_readiness.provider_endpoint_leak.json"
)


def auth_headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    return {"Authorization": f"Bearer {token.access_token}"}


def test_route_health_api_requires_service_claim() -> None:
    response = TestClient(app).get("/api/v1/provider-route-health")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_route_health_api_returns_schema_valid_mock_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_MO_PROVIDER_MODE", "mock")
    PROVIDER_READINESS.clear()

    response = TestClient(app).get(
        "/api/v1/provider-route-health",
        headers=auth_headers(),
    )
    payload = response.json()
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).validate(payload)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["summary"]["route_count"] == 3


def test_route_health_api_returns_degraded_live_snapshot_with_http_200() -> None:
    service = ProviderReadinessService(
        environ={
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://private.local/embeddings",
            "NEX_MO_REMOTE_RERANKER_URL": "http://private.local/rerank",
            "NEX_MO_VLLM_BASE_URL": "http://private.local:9111",
        },
        requester=lambda *args, **kwargs: httpx.Response(503),
        now=lambda: datetime(2026, 9, 30, tzinfo=UTC),
    )
    isolated_app = FastAPI()
    register_provider_readiness_routes(isolated_app, service=service)

    response = TestClient(isolated_app).get(
        "/api/v1/provider-route-health",
        headers=auth_headers(),
    )
    serialized = json.dumps(response.json())

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert all(route["status"] == "DEGRADED" for route in response.json()["routes"])
    assert "private.local" not in serialized


def test_route_health_api_returns_safe_configuration_failure() -> None:
    service = ProviderReadinessService(
        environ={"NEX_MO_PROVIDER_MODE": "invalid"},
        now=lambda: datetime(2026, 9, 30, tzinfo=UTC),
    )
    isolated_app = FastAPI()
    register_provider_readiness_routes(isolated_app, service=service)

    response = TestClient(isolated_app).get(
        "/api/v1/provider-route-health",
        headers=auth_headers(),
    )
    Draft202012Validator(json.loads(SCHEMA_PATH.read_text())).validate(response.json())

    assert response.status_code == 200
    assert response.json()["cache_status"] == "MISS"
    assert response.json()["routes"] == []


def test_provider_readiness_contract_accepts_positive_and_rejects_leak() -> None:
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))

    validator.validate(json.loads(EXAMPLE_PATH.read_text()))
    with pytest.raises(ValidationError):
        validator.validate(json.loads(NEGATIVE_PATH.read_text()))


def test_openapi_documents_authenticated_route_health_schema() -> None:
    document = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-mo.openapi.yaml").read_text()
    )
    operation = document["paths"]["/api/v1/provider-route-health"]["get"]

    assert operation["operationId"] == "getMoProviderRouteHealth"
    assert operation["security"] == [{"serviceBearer": []}]
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ProviderReadiness"}
    assert document["components"]["schemas"]["ProviderReadiness"][
        "x-nex-canonical-json-schema"
    ] == "schemas/service/nex_mo/provider_readiness.v1.schema.json"


def test_auth_fallback_omits_internal_validation_details(monkeypatch) -> None:
    monkeypatch.setattr(
        provider_auth,
        "validate_authorization_header",
        lambda *args, **kwargs: SimpleNamespace(
            ok=False,
            error_code=None,
            detail=None,
        ),
    )
    isolated_app = FastAPI()

    @isolated_app.get("/test")
    def test_route(request: Request):
        return provider_auth.authorize_mo_service_request(request, None)

    response = TestClient(isolated_app).get("/test")

    assert response.status_code == 401
    assert response.json()["error_code"] == "SERVICE_CLAIM_INVALID"
    assert response.json()["detail"] == "MO requires a valid service claim."


def test_route_health_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_route_health_api()
    assert "route_health_api=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_provider_route_health_api", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "routes=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_route_health_api",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
