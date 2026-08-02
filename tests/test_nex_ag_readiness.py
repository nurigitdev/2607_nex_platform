from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

import nex_ag.readiness as ag_readiness
from nex_ag.readiness import (
    HttpServiceStatusClient,
    build_readiness_projection,
    normalize_service_projection,
    register_readiness_routes,
    service_unavailable_projection,
    summarize_services,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


class FakeStatusClient:
    def __init__(self, statuses: dict[str, dict[str, Any]]) -> None:
        self.statuses = statuses
        self.calls: list[tuple[str, str]] = []

    def fetch_status(self, service_id: str, base_url: str) -> dict[str, Any]:
        self.calls.append((service_id, base_url))
        return self.statuses[service_id]


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {"Authorization": f"Bearer {issued.access_token}"}


def ready_projection(service_id: str) -> dict[str, Any]:
    return {
        "service_id": service_id,
        "base_url": f"http://{service_id}.test",
        "health_status": "HEALTHY",
        "readiness_status": "READY",
        "version": "0.0.0-test",
        "contract_catalog_version": "slice-0009",
        "observed_status": "READY",
        "failures": [],
    }


def test_normalize_service_projection_marks_ready() -> None:
    projection = normalize_service_projection(
        service_id="nex-cx",
        base_url="http://cx.test",
        health={"health_status": "HEALTHY"},
        ready={"readiness_status": "READY"},
        version={"version": "1", "contract_catalog_version": "slice-0009"},
    )

    assert projection["observed_status"] == "READY"
    assert projection["contract_catalog_version"] == "slice-0009"


def test_normalize_service_projection_marks_not_ready() -> None:
    projection = normalize_service_projection(
        service_id="nex-cx",
        base_url="http://cx.test",
        health={"health_status": "HEALTHY"},
        ready={"readiness_status": "NOT_READY"},
        version={},
    )

    assert projection["observed_status"] == "NOT_READY"


def test_normalize_service_projection_marks_degraded_for_endpoint_failure() -> None:
    projection = normalize_service_projection(
        service_id="nex-cx",
        base_url="http://cx.test",
        health={"health_status": "HEALTHY"},
        ready={"readiness_status": "READY"},
        version={},
        failures=[{"endpoint": "version", "error_code": "SERVICE_ENDPOINT_FAILED"}],
    )

    assert projection["observed_status"] == "DEGRADED"


def test_service_unavailable_projection() -> None:
    projection = service_unavailable_projection("nex-cx", "http://cx.test", "boom")

    assert projection["observed_status"] == "UNAVAILABLE"
    assert projection["failures"][0]["error_code"] == "SERVICE_STATUS_UNAVAILABLE"


def test_summarize_services_counts_statuses() -> None:
    summary = summarize_services(
        [
            {"observed_status": "READY"},
            {"observed_status": "NOT_READY"},
            {"observed_status": "DEGRADED"},
            {"observed_status": "UNAVAILABLE"},
        ]
    )

    assert summary == {
        "total": 4,
        "ready": 1,
        "not_ready": 1,
        "degraded": 1,
        "unavailable": 1,
    }


def test_build_readiness_projection_sorts_services() -> None:
    statuses = {
        service_id: ready_projection(service_id)
        for service_id in ["nex-cx", "nex-oa"]
    }
    client = FakeStatusClient(statuses)

    projection = build_readiness_projection(
        client,
        {"nex-oa": "http://oa.test", "nex-cx": "http://cx.test"},
    )

    assert [service["service_id"] for service in projection["services"]] == [
        "nex-cx",
        "nex-oa",
    ]
    assert projection["summary"]["ready"] == 2
    assert client.calls == [("nex-cx", "http://cx.test"), ("nex-oa", "http://oa.test")]


def test_readiness_endpoint_requires_service_claim() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_readiness_routes(app, status_client=FakeStatusClient({}), service_endpoints={})

    response = TestClient(app).get("/admin/v1/readiness/services")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_readiness_endpoint_returns_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    statuses = {"nex-cx": ready_projection("nex-cx")}
    register_readiness_routes(
        app,
        status_client=FakeStatusClient(statuses),
        service_endpoints={"nex-cx": "http://cx.test"},
    )

    response = TestClient(app).get(
        "/admin/v1/readiness/services",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == "ag_readiness_projection.v1"
    assert payload["summary"]["ready"] == 1


def test_http_service_status_client_reads_service_endpoints(monkeypatch) -> None:
    calls: list[str] = []

    def fake_get(url: str, timeout: float):
        calls.append(url)
        if url.endswith("/health"):
            return httpx.Response(200, json={"health_status": "HEALTHY"})
        if url.endswith("/ready"):
            return httpx.Response(200, json={"readiness_status": "READY"})
        return httpx.Response(
            200,
            json={"version": "0.0.0-test", "contract_catalog_version": "slice-0009"},
        )

    monkeypatch.setattr(ag_readiness.httpx, "get", fake_get)

    projection = HttpServiceStatusClient().fetch_status("nex-cx", "http://cx.test")

    assert projection["observed_status"] == "READY"
    assert calls == [
        "http://cx.test/health",
        "http://cx.test/ready",
        "http://cx.test/version",
    ]


def test_http_service_status_client_handles_unavailable_service(monkeypatch) -> None:
    def fake_get(url: str, timeout: float):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(ag_readiness.httpx, "get", fake_get)

    projection = HttpServiceStatusClient().fetch_status("nex-cx", "http://cx.test")

    assert projection["observed_status"] == "UNAVAILABLE"
