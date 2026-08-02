from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from nex_runtime import SERVICE_SPECS, build_service_app
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
