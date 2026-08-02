from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
import nex_runtime.app as runtime_app


class FakeCursor:
    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[int]:
        return (1,)


class FakeConnection:
    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor()


def test_service_specs_cover_five_backend_services() -> None:
    assert set(SERVICE_SPECS) == {
        "nex-oa",
        "nex-ag",
        "nex-ae-api",
        "nex-cx",
        "nex-mo",
    }
    assert SERVICE_SPECS["nex-oa"].default_port == 8101
    assert SERVICE_SPECS["nex-mo"].database_env == "NEX_MO_DATABASE_URL"


def test_root_health_and_version_use_service_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEX_VERSION", "9.9.9-test")
    monkeypatch.setenv("NEX_PROFILE", "test")
    monkeypatch.setenv("NEX_BUILD_SHA", "abc123")

    client = TestClient(build_service_app(SERVICE_SPECS["nex-cx"]))

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["links"] == {
        "health": "/health",
        "ready": "/ready",
        "version": "/version",
    }

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["health_status"] == "HEALTHY"
    assert health.json()["profile"] == "test"

    version = client.get("/version")
    assert version.status_code == 200
    assert version.json()["version"] == "9.9.9-test"
    assert version.json()["build_sha"] == "abc123"
    assert version.json()["contract_catalog_version"] == "slice-0022"


def test_ready_returns_503_when_database_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = SERVICE_SPECS["nex-ae-api"]
    monkeypatch.delenv(spec.database_env, raising=False)

    client = TestClient(build_service_app(spec))
    response = client.get("/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["readiness_status"] == "NOT_READY"
    assert payload["checks"][0]["error_code"] == "DATABASE_URL_MISSING"


def test_ready_returns_ready_when_database_check_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_connect(database_url: str, connect_timeout: int) -> FakeConnection:
        calls.append((database_url, connect_timeout))
        return FakeConnection()

    spec = SERVICE_SPECS["nex-oa"]
    monkeypatch.setenv(spec.database_env, "postgresql://example")
    monkeypatch.setattr(runtime_app.psycopg, "connect", fake_connect)

    client = TestClient(build_service_app(spec))
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["readiness_status"] == "READY"
    assert response.json()["checks"][0]["ok"] is True
    assert calls == [("postgresql://example", 2)]


def test_ready_reports_database_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connect(database_url: str, connect_timeout: int) -> FakeConnection:
        raise RuntimeError("database unavailable")

    spec = SERVICE_SPECS["nex-ag"]
    monkeypatch.setenv(spec.database_env, "postgresql://example")
    monkeypatch.setattr(runtime_app.psycopg, "connect", fail_connect)

    client = TestClient(build_service_app(spec))
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"][0]["error_code"] == "DATABASE_CONNECTION_FAILED"


@pytest.mark.parametrize("service_id", sorted(SERVICE_SPECS))
def test_service_claim_endpoint_accepts_valid_mock_token(service_id: str) -> None:
    issued = issue_mock_service_token(service_id="nex-oa", audience=service_id)
    client = TestClient(build_service_app(SERVICE_SPECS[service_id]))

    response = client.get(
        "/internal/v1/auth/service-claim",
        headers={"Authorization": f"Bearer {issued.access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["claim_status"] == "VALID"
    assert response.json()["claims"]["audience"] == service_id


def test_service_claim_endpoint_rejects_missing_token_with_problem_json() -> None:
    client = TestClient(build_service_app(SERVICE_SPECS["nex-cx"]))

    response = client.get(
        "/internal/v1/auth/service-claim",
        headers={
            "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert payload["request_id"] == "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
    assert payload["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_oa_issues_and_introspects_mock_service_token() -> None:
    client = TestClient(build_service_app(SERVICE_SPECS["nex-oa"]))

    token_response = client.post(
        "/api/v1/auth/service-token",
        json={"service_id": "nex-ae-api", "audience": "nex-cx"},
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["token_type"] == "Bearer"
    assert token_payload["claims"]["service_id"] == "nex-ae-api"

    introspect_response = client.post(
        "/api/v1/auth/introspect",
        json={
            "token": token_payload["access_token"],
            "audience": "nex-cx",
            "required_scopes": ["service:call"],
        },
    )

    assert introspect_response.status_code == 200
    assert introspect_response.json()["active"] is True


def test_oa_rejects_invalid_service_token_request_with_problem_json() -> None:
    client = TestClient(build_service_app(SERVICE_SPECS["nex-oa"]))

    response = client.post(
        "/api/v1/auth/service-token",
        json={"service_id": "unknown", "audience": "nex-cx"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "SERVICE_TOKEN_REQUEST_INVALID"


def test_oa_introspection_reports_inactive_for_invalid_token() -> None:
    client = TestClient(build_service_app(SERVICE_SPECS["nex-oa"]))

    response = client.post("/api/v1/auth/introspect", json={"token": "invalid"})

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert response.json()["error_code"] == "TOKEN_FORMAT_INVALID"


@pytest.mark.parametrize(
    ("module_name", "service_id"),
    [
        ("nex_oa.main", "nex-oa"),
        ("nex_ag.main", "nex-ag"),
        ("nex_ae_api.main", "nex-ae-api"),
        ("nex_cx.main", "nex-cx"),
        ("nex_mo.main", "nex-mo"),
    ],
)
def test_service_entrypoints_import(module_name: str, service_id: str) -> None:
    module = importlib.import_module(module_name)

    assert module.app.title == f"{SERVICE_SPECS[service_id].display_name} Service"
