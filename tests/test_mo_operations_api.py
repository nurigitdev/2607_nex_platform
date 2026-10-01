from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nex_mo.operations_api import register_operations_routes
from nex_runtime import issue_mock_service_token
import run_mo_operations_api as runner


class StubOperationsService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.force_refresh: bool | None = None

    def snapshot(self, *, force_refresh: bool = False):
        self.force_refresh = force_refresh
        if self.fail:
            raise RuntimeError("private endpoint and credential details")
        return {
            "operations_schema_version": "mo_operations_snapshot.v1",
            "provider_mode": "mock",
            "operations_status": "READY",
            "generated_at": "2026-10-01T00:00:00Z",
            "acceptance_status": "NOT_RUN",
            "failure_code": None,
            "sources": [],
            "capabilities": [],
            "summary": {"source_count": 0, "capability_count": 0},
        }


def _client(service: StubOperationsService) -> TestClient:
    app = FastAPI()
    register_operations_routes(app, service=service)
    return TestClient(app)


def _headers(*, audience: str = "nex-mo") -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience=audience)
    return {"Authorization": f"Bearer {token.access_token}"}


def test_operations_snapshot_requires_service_authentication() -> None:
    client = _client(StubOperationsService())

    missing = client.get("/api/v1/operations-snapshot")
    wrong = client.get(
        "/api/v1/operations-snapshot",
        headers=_headers(audience="nex-cx"),
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_operations_snapshot_returns_safe_projection_and_refreshes() -> None:
    service = StubOperationsService()
    response = _client(service).get(
        "/api/v1/operations-snapshot?force_refresh=true",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["operations_status"] == "READY"
    assert service.force_refresh is True


def test_operations_snapshot_failure_is_safe_problem_response() -> None:
    response = _client(StubOperationsService(fail=True)).get(
        "/api/v1/operations-snapshot",
        headers=_headers(),
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "MO_OPERATIONS_SNAPSHOT_UNAVAILABLE"
    assert "private endpoint" not in json.dumps(response.json())


def test_operations_api_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    evidence = runner.run_mo_operations_api()
    assert evidence["status"] == "PASS"
    assert "auth=401/200" in runner.summary_line(evidence)
    monkeypatch.setattr(runner, "run_mo_operations_api", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1186" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_operations_api",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
