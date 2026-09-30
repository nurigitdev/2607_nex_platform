from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import nex_runtime.app as runtime_app
from nex_runtime import SERVICE_SPECS, build_service_app
from nex_mo.main import PROVIDER_READINESS, app
import run_mo_provider_ready_route as runner


def database_check(*, ok: bool = True) -> dict[str, object]:
    return {
        "name": "database",
        "ok": ok,
        "database_env": "NEX_MO_DATABASE_URL",
        "error_code": None if ok else "DATABASE_CONNECTION_FAILED",
    }


def test_shared_ready_route_composes_optional_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_app,
        "check_database_readiness",
        lambda database_env: database_check(),
    )
    additional_calls = 0

    def additional_check() -> dict[str, object]:
        nonlocal additional_calls
        additional_calls += 1
        return {"name": "provider_routes", "ok": True, "route_count": 3}

    client = TestClient(
        build_service_app(
            SERVICE_SPECS["nex-mo"],
            readiness_checks=(additional_check,),
        )
    )
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["readiness_status"] == "READY"
    assert [check["name"] for check in response.json()["checks"]] == [
        "database",
        "provider_routes",
    ]
    assert additional_calls == 1


@pytest.mark.parametrize(
    "additional_check",
    [
        lambda: {"name": "provider_routes", "ok": False},
        lambda: {"name": "provider_routes", "ok": "yes"},
        lambda: {"ok": True},
        lambda: "invalid",
        lambda: (_ for _ in ()).throw(RuntimeError("private failure detail")),
    ],
)
def test_shared_ready_route_fails_closed_for_additional_check(
    monkeypatch: pytest.MonkeyPatch,
    additional_check,
) -> None:
    monkeypatch.setattr(
        runtime_app,
        "check_database_readiness",
        lambda database_env: database_check(),
    )
    client = TestClient(
        build_service_app(
            SERVICE_SPECS["nex-mo"],
            readiness_checks=(additional_check,),
        )
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["readiness_status"] == "NOT_READY"
    assert "private failure detail" not in json.dumps(response.json())


def test_services_without_additional_checks_preserve_database_only_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_app,
        "check_database_readiness",
        lambda database_env: database_check(),
    )

    response = TestClient(build_service_app(SERVICE_SPECS["nex-cx"])).get("/ready")

    assert response.status_code == 200
    assert [check["name"] for check in response.json()["checks"]] == ["database"]


def test_mo_main_wires_provider_readiness_after_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_MO_PROVIDER_MODE", "mock")
    monkeypatch.setattr(
        runtime_app,
        "check_database_readiness",
        lambda database_env: database_check(),
    )
    PROVIDER_READINESS.clear()

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert [check["name"] for check in response.json()["checks"]] == [
        "database",
        "provider_routes",
    ]
    assert app.state.provider_readiness_service is PROVIDER_READINESS
    assert response.json()["checks"][1]["summary"]["status_counts"]["READY"] == 3


def test_mo_ready_requires_both_database_and_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEX_MO_PROVIDER_MODE", "mock")
    monkeypatch.setattr(
        runtime_app,
        "check_database_readiness",
        lambda database_env: database_check(ok=False),
    )
    PROVIDER_READINESS.clear()

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["checks"][0]["ok"] is False
    assert response.json()["checks"][1]["ok"] is True


def test_ready_route_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_ready_route()
    assert "provider_ready_route=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_provider_ready_route", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "checks=2" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_ready_route",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
