from __future__ import annotations

from datetime import UTC, datetime
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nex_mo.runtime_observability_api import register_runtime_observability_routes
from nex_mo.runtime_observability_service import RuntimeObservabilityService
from nex_runtime import issue_mock_service_token
import run_mo_runtime_observability_api as runner


NOW = datetime(2026, 9, 30, tzinfo=UTC)


def auth_headers(
    *, service_id: str = "nex-ag", audience: str = "nex-mo"
) -> dict[str, str]:
    token = issue_mock_service_token(service_id=service_id, audience=audience)
    return {"Authorization": f"Bearer {token.access_token}"}


def build_app(service: RuntimeObservabilityService | None = None) -> FastAPI:
    app = FastAPI()
    register_runtime_observability_routes(
        app,
        service=service
        or RuntimeObservabilityService(environ={}, now=lambda: NOW),
    )
    return app


def test_runtime_observability_api_requires_valid_service_claim() -> None:
    client = TestClient(build_app())
    missing = client.get("/api/v1/model-runtime-observability")
    wrong_audience = client.get(
        "/api/v1/model-runtime-observability",
        headers=auth_headers(audience="nex-cx"),
    )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"


def test_runtime_observability_api_returns_privacy_safe_snapshot() -> None:
    response = TestClient(build_app()).get(
        "/api/v1/model-runtime-observability",
        headers=auth_headers(),
    )
    serialized = json.dumps(response.json())

    assert response.status_code == 200
    assert response.json()["runtime_status"] == "HEALTHY"
    assert len(response.json()["models"]) == 3
    for private in (
        "ssh_target",
        "provider_api_key",
        "process_id",
        "process_command_line",
        "model_path",
        "gpu_uuid",
    ):
        assert private not in serialized


def test_runtime_observability_api_passes_force_refresh() -> None:
    service = RuntimeObservabilityService(environ={}, now=lambda: NOW)
    client = TestClient(build_app(service))
    client.get("/api/v1/model-runtime-observability", headers=auth_headers())
    refreshed = client.get(
        "/api/v1/model-runtime-observability?force_refresh=true",
        headers=auth_headers(),
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["cache_status"] == "REFRESHED"


def test_runtime_observability_api_returns_safe_unknown_on_service_failure() -> None:
    service = RuntimeObservabilityService(
        environ={"NEX_MO_RUNTIME_OBSERVABILITY_MODE": "invalid"},
        now=lambda: NOW,
    )
    response = TestClient(build_app(service)).get(
        "/api/v1/model-runtime-observability",
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["runtime_status"] == "UNKNOWN"
    assert response.json()["failure_code"] == "runtime_observation_failed"


def test_runtime_observability_api_is_not_registered_as_readiness() -> None:
    app = build_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/model-runtime-observability" in paths
    assert "/ready" not in paths


def test_api_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_observability_api()
    assert "runtime_observability_api=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_runtime_observability_api", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "authorized=200" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observability_api",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
