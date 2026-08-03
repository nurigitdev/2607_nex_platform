from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

import nex_ag.readiness as ag_readiness
from nex_ag.readiness import (
    HttpProviderTelemetryClient,
    HttpServiceStatusClient,
    build_provider_readiness_projection,
    build_readiness_projection,
    normalize_provider_telemetry_projection,
    provider_telemetry_unavailable_projection,
    normalize_service_projection,
    provider_readiness_status,
    register_readiness_routes,
    service_unavailable_projection,
    summarize_provider_telemetry,
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


class FakeProviderTelemetryClient:
    def __init__(self, projection: dict[str, Any]) -> None:
        self.projection = projection
        self.calls: list[str] = []

    def fetch_provider_telemetry(self, mo_base_url: str) -> dict[str, Any]:
        self.calls.append(mo_base_url)
        return dict(self.projection)


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


def mo_provider_telemetry_payload(
    *,
    provider_mode: str = "live",
    configured: bool = True,
    failure_count: int = 0,
    degraded_count: int = 0,
) -> dict[str, Any]:
    return {
        "data": [
            {
                "capability": "embedding",
                "endpoint_env": "NEX_MO_REMOTE_EMBEDDING_URL",
                "configured": configured,
                "request_shape": "openai_embeddings",
                "model_name": "EmbeddingA",
                "model_revision": "EmbeddingA@rev",
                "deployment_id": "remote-embedding-a",
                "authorization_env": "NEX_MO_REMOTE_EMBEDDING_API_KEY",
                "authorization_configured": True,
                "request_count": 2,
                "success_count": 1,
                "failure_count": failure_count,
                "retryable_failure_count": failure_count,
                "degraded_count": degraded_count,
                "last_outcome": "failure" if failure_count else "success",
                "last_observed_at": "2026-08-03T00:00:00Z",
                "last_latency_ms": 12,
                "last_status_code": 503 if failure_count else 200,
                "last_error_code": (
                    "mo.remote_embedding_http_error" if failure_count else None
                ),
                "last_failure_kind": "upstream_5xx" if failure_count else None,
                "last_upstream_status_code": 503 if failure_count else None,
            }
        ],
        "meta": {
            "provider_mode": provider_mode,
            "schema_version": "mo_provider_telemetry_snapshot.v1",
        },
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
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert projection["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
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
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["projection_schema_version"] == "ag_readiness_projection.v1"
    assert payload["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert payload["summary"]["ready"] == 1


def test_provider_telemetry_projection_marks_ready_and_summarizes_safely() -> None:
    projection = normalize_provider_telemetry_projection(
        mo_base_url="http://mo.test",
        telemetry=mo_provider_telemetry_payload(),
    )

    assert projection["observed_status"] == "READY"
    assert projection["provider_mode"] == "live"
    assert projection["summary"] == {
        "total": 1,
        "configured": 1,
        "unconfigured": 0,
        "requests": 2,
        "successes": 1,
        "failures": 0,
        "retryable_failures": 0,
        "degraded": 0,
    }
    assert projection["providers"][0]["deployment_id"] == "remote-embedding-a"
    assert "api_key" not in str(projection).lower()
    assert "dgx.local" not in str(projection)


def test_provider_telemetry_projection_marks_live_unconfigured_not_ready() -> None:
    projection = normalize_provider_telemetry_projection(
        mo_base_url="http://mo.test",
        telemetry=mo_provider_telemetry_payload(configured=False),
    )

    assert projection["observed_status"] == "NOT_READY"
    assert projection["summary"]["unconfigured"] == 1


def test_provider_telemetry_projection_marks_degraded_for_failures() -> None:
    projection = normalize_provider_telemetry_projection(
        mo_base_url="http://mo.test",
        telemetry=mo_provider_telemetry_payload(failure_count=1, degraded_count=1),
    )

    assert projection["observed_status"] == "DEGRADED"
    assert projection["summary"]["failures"] == 1
    assert projection["summary"]["retryable_failures"] == 1
    assert projection["summary"]["degraded"] == 1


def test_provider_telemetry_projection_handles_malformed_payloads_and_items() -> None:
    unavailable = normalize_provider_telemetry_projection(
        mo_base_url="http://mo.test",
        telemetry={"meta": {"provider_mode": "live"}},
    )
    malformed = normalize_provider_telemetry_projection(
        mo_base_url="http://mo.test",
        telemetry={"data": ["bad"], "meta": {"provider_mode": "live"}},
    )

    assert unavailable["observed_status"] == "UNAVAILABLE"
    assert unavailable["failures"][0]["error_code"] == "MO_PROVIDER_TELEMETRY_UNAVAILABLE"
    assert malformed["observed_status"] == "DEGRADED"
    assert malformed["failures"][0]["error_code"] == "PROVIDER_TELEMETRY_ITEM_INVALID"


def test_provider_readiness_status_policy_edges() -> None:
    assert provider_readiness_status(provider_mode="mock", providers=[], failures=[]) == (
        "NOT_READY"
    )
    assert provider_readiness_status(
        provider_mode="mock",
        providers=[{"configured": False, "failure_count": 0, "degraded_count": 0}],
        failures=[],
    ) == "READY"
    assert provider_readiness_status(
        provider_mode="live",
        providers=[{"configured": False, "failure_count": 0, "degraded_count": 0}],
        failures=[],
    ) == "NOT_READY"
    assert provider_readiness_status(
        provider_mode="live",
        providers=[{"configured": True, "failure_count": 1, "degraded_count": 0}],
        failures=[],
    ) == "DEGRADED"


def test_summarize_provider_telemetry_counts_rows() -> None:
    summary = summarize_provider_telemetry(
        [
            {
                "configured": True,
                "request_count": 3,
                "success_count": 2,
                "failure_count": 1,
                "retryable_failure_count": 1,
                "degraded_count": 1,
            },
            {
                "configured": False,
                "request_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "retryable_failure_count": 0,
                "degraded_count": 0,
            },
        ]
    )

    assert summary == {
        "total": 2,
        "configured": 1,
        "unconfigured": 1,
        "requests": 3,
        "successes": 2,
        "failures": 1,
        "retryable_failures": 1,
        "degraded": 1,
    }


def test_build_provider_readiness_projection_uses_mo_endpoint_and_trace() -> None:
    client = FakeProviderTelemetryClient(
        normalize_provider_telemetry_projection(
            mo_base_url="http://mo.test",
            telemetry=mo_provider_telemetry_payload(),
        )
    )

    projection = build_provider_readiness_projection(
        client,
        mo_base_url="http://mo.test",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert client.calls == ["http://mo.test"]
    assert projection["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert projection["observed_status"] == "READY"


def test_provider_readiness_endpoint_requires_service_claim() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_readiness_routes(
        app,
        status_client=FakeStatusClient({}),
        provider_client=FakeProviderTelemetryClient({}),
        service_endpoints={},
    )

    response = TestClient(app).get("/admin/v1/readiness/providers")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_provider_readiness_endpoint_returns_mo_provider_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    projection = normalize_provider_telemetry_projection(
        mo_base_url="http://mo.test",
        telemetry=mo_provider_telemetry_payload(),
    )
    provider_client = FakeProviderTelemetryClient(projection)
    register_readiness_routes(
        app,
        status_client=FakeStatusClient({}),
        provider_client=provider_client,
        service_endpoints={"nex-mo": "http://mo.test"},
    )

    response = TestClient(app).get(
        "/admin/v1/readiness/providers",
        headers={
            **auth_headers(),
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert provider_client.calls == ["http://mo.test"]
    assert payload["projection_schema_version"] == (
        "ag_mo_provider_readiness_projection.v1"
    )
    assert payload["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert payload["observed_status"] == "READY"


def test_http_provider_telemetry_client_reads_mo_endpoint(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, headers: dict[str, str], timeout: float):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return httpx.Response(200, json=mo_provider_telemetry_payload())

    monkeypatch.setattr(ag_readiness.httpx, "get", fake_get)

    projection = HttpProviderTelemetryClient(
        timeout_seconds=3.5,
        service_token="safe-test-token",
    ).fetch_provider_telemetry("http://mo.test/")

    assert projection["observed_status"] == "READY"
    assert calls == [
        {
            "url": "http://mo.test/api/v1/provider-telemetry",
            "headers": {"Authorization": "Bearer safe-test-token"},
            "timeout": 3.5,
        }
    ]


def test_http_provider_telemetry_client_handles_unavailable_and_http_errors(
    monkeypatch,
) -> None:
    def offline_get(url: str, headers: dict[str, str], timeout: float):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(ag_readiness.httpx, "get", offline_get)
    offline = HttpProviderTelemetryClient().fetch_provider_telemetry("http://mo.test")
    assert offline["observed_status"] == "UNAVAILABLE"

    def problem_get(url: str, headers: dict[str, str], timeout: float):
        return httpx.Response(503, json={"error_code": "down"})

    monkeypatch.setattr(ag_readiness.httpx, "get", problem_get)
    problem = HttpProviderTelemetryClient().fetch_provider_telemetry("http://mo.test")
    assert problem["observed_status"] == "UNAVAILABLE"
    assert "HTTP 503" in problem["failures"][0]["detail"]


def test_provider_telemetry_unavailable_projection_shape() -> None:
    projection = provider_telemetry_unavailable_projection("http://mo.test", "offline")

    assert projection["observed_status"] == "UNAVAILABLE"
    assert projection["summary"]["total"] == 0
    assert projection["failures"][0]["detail"] == "offline"


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
