from __future__ import annotations

import importlib
from pathlib import Path
from typing import Self

import nex_runtime.database as runtime_database
import pytest
import run_all_services
import run_service
import run_tiered_quality_gate
import yaml
from fastapi.testclient import TestClient
from nex_ag.service_auth import resolve_ag_outbound_service_token
from nex_eos import EosConfigurationError, load_eos_settings
from nex_eos.app import CONTRACT_CATALOG_VERSION, SERVICE_SPEC, create_eos_app
from nex_runtime import (
    SERVICE_RUNTIME_OPERATION_SPECS,
    SERVICE_SPECS,
    issue_mock_service_token,
)
from nex_runtime.database import service_database_env_prefix

ROOT = Path(__file__).parents[1]


class FakeCursor:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        assert sql.lower() == "select current_database(), current_user"

    def fetchone(self) -> tuple[str, str]:
        return ("nex_eos_test", "nex_eos_user")


class FakeConnection:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor()


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s07",
        "NEX_BUILD_SHA": "p8s07test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    values.update(overrides)
    return values


def test_settings_load_fail_closed_and_expose_only_safe_identity() -> None:
    settings = load_eos_settings(_environment())

    assert settings.public_projection() == {
        "service_id": "nex-eos",
        "profile": "test",
        "version": "2.1.0-p8-s07",
        "build_sha": "p8s07test",
        "database_env": "NEX_EOS_DATABASE_URL",
    }


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("NEX_EOS_SERVICE_ID", "nex-cx", "must be nex-eos"),
        ("NEX_PROFILE", "unknown", "unsupported EOS runtime profile"),
        ("NEX_PROFILE", " test", "must not contain outer whitespace"),
        ("NEX_VERSION", "bad version", "invalid format"),
        ("NEX_BUILD_SHA", "", "non-empty string"),
    ],
)
def test_settings_reject_invalid_startup_configuration(
    name: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(EosConfigurationError, match=message):
        load_eos_settings(_environment(**{name: value}))


def test_settings_reject_non_string_identity_value() -> None:
    environment: dict[str, object] = dict(_environment())
    environment["NEX_BUILD_SHA"] = 7

    with pytest.raises(EosConfigurationError, match="non-empty string"):
        load_eos_settings(environment)  # type: ignore[arg-type]


def test_app_startup_exposes_only_platform_shell_routes() -> None:
    app = create_eos_app(environ=_environment())
    client = TestClient(app)

    assert app.title == "NeX Enterprise Operations System Service"
    assert app.state.eos_settings.service_id == "nex-eos"
    assert (
        app.state.eos_dependencies.service_token_admission.expected_audience
        == "nex-eos"
    )
    assert client.get("/").json()["service_id"] == "nex-eos"
    assert client.get("/health").json()["health_status"] == "HEALTHY"

    routes = {route.path for route in app.routes}
    assert {
        "/",
        "/health",
        "/ready",
        "/version",
        "/internal/v1/auth/service-claim",
        "/internal/v1/auth/service-claim/active",
        "/internal/v1/auth/service-token-runtime",
    }.issubset(routes)
    assert not any(path.startswith("/api/") for path in routes)


def test_readiness_fails_closed_without_database_url() -> None:
    response = TestClient(create_eos_app(environ=_environment())).get("/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["readiness_status"] == "NOT_READY"
    assert payload["checks"][0]["error_code"] == "DATABASE_URL_MISSING"
    assert payload["checks"][1] == {
        "name": "eos_service_configuration",
        "ok": True,
        "service_id": "nex-eos",
        "profile": "test",
        "version": "2.1.0-p8-s07",
        "build_sha": "p8s07test",
    }


def test_readiness_checks_database_without_leaking_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_connect(database_url: str, connect_timeout: int) -> FakeConnection:
        calls.append((database_url, connect_timeout))
        return FakeConnection()

    database_url = "postgresql://nex_eos_user:secret@localhost/nex_eos_test"
    monkeypatch.setattr(runtime_database.psycopg, "connect", fake_connect)
    response = TestClient(
        create_eos_app(
            environ=_environment(NEX_EOS_DATABASE_URL=database_url),
        )
    ).get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_status"] == "READY"
    assert payload["checks"][0]["database_name"] == "nex_eos_test"
    assert payload["checks"][0]["database_user"] == "nex_eos_user"
    assert "secret" not in response.text
    assert calls == [(database_url, 2)]


def test_version_build_identity_is_bound_to_validated_settings() -> None:
    response = TestClient(
        create_eos_app(
            environ=_environment(
                NEX_VERSION="2.1.0-rc1",
                NEX_BUILD_SHA="abc1234",
            )
        )
    ).get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "service_id": "nex-eos",
        "service_name": "NeX Enterprise Operations System",
        "version": "2.1.0-rc1",
        "api_version": "v1",
        "contract_catalog_version": CONTRACT_CATALOG_VERSION,
        "build_sha": "abc1234",
    }


def test_service_trust_baseline_accepts_scoped_caller_and_rejects_wrong_audience() -> (
    None
):
    client = TestClient(create_eos_app(environ=_environment()))
    accepted = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-eos",
    )
    wrong_audience = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
    )

    claim = client.get(
        "/internal/v1/auth/service-claim",
        headers={"Authorization": f"Bearer {accepted.access_token}"},
    )
    active = client.post(
        "/internal/v1/auth/service-claim/active",
        headers={"Authorization": f"Bearer {accepted.access_token}"},
    )
    rejected = client.get(
        "/internal/v1/auth/service-claim",
        headers={"Authorization": f"Bearer {wrong_audience.access_token}"},
    )

    assert claim.status_code == 200
    assert claim.json()["claims"]["audience"] == "nex-eos"
    assert active.status_code == 200
    assert active.json()["claim_status"] == "ACTIVE"
    assert rejected.status_code == 403
    assert wrong_audience.access_token not in rejected.text


def test_service_token_runtime_projection_is_protected_and_redacted() -> None:
    client = TestClient(create_eos_app(environ=_environment()))
    token = issue_mock_service_token(service_id="nex-oa", audience="nex-eos")

    missing = client.get("/internal/v1/auth/service-token-runtime")
    accepted = client.get(
        "/internal/v1/auth/service-token-runtime",
        headers={"Authorization": f"Bearer {token.access_token}"},
    )

    assert missing.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["service_id"] == "nex-eos"
    assert accepted.json()["rollout_profile"] == "TEST_MOCK"
    assert token.access_token not in accepted.text


def test_common_registration_and_developer_tools_include_eos() -> None:
    assert SERVICE_SPEC is SERVICE_SPECS["nex-eos"]
    assert SERVICE_SPEC.default_port == 8107
    assert service_database_env_prefix("nex-eos") == "NEX_EOS"
    assert "nex-eos" not in SERVICE_RUNTIME_OPERATION_SPECS
    assert run_service.SERVICE_MODULES["nex-eos"] == "nex_eos.main:app"
    assert run_all_services.SERVICES[-1] == "nex-eos"
    assert "nex-eos" in run_tiered_quality_gate.SERVICE_PROFILES

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    quality_gate = (ROOT / "scripts/quality/run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    environment_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert '"services/nex-eos"' in pyproject
    assert "services/nex-eos" in quality_gate
    assert "NEX_EOS_BASE_URL=http://127.0.0.1:8107" in environment_example
    assert "NEX_EOS_DATABASE_URL=postgresql://nex_eos_user:" in environment_example


def test_ag_signed_outbound_trust_can_target_eos() -> None:
    token = resolve_ag_outbound_service_token(
        None,
        audience="nex-eos",
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
            "NEX_AG_TO_EOS_SERVICE_TOKEN": "signed-eos-token",
        },
    )

    assert token == "signed-eos-token"


def test_main_module_exports_executable_app() -> None:
    module = importlib.import_module("nex_eos.main")

    assert module.app.state.eos_settings.service_id == "nex-eos"
    assert module.SERVICE_SPEC is SERVICE_SPEC


def test_openapi_preserves_service_shell_contract_as_domain_paths_evolve() -> None:
    contract = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )

    assert contract["info"]["version"].startswith("2.1.0-p8-s")
    assert contract["servers"] == [{"url": "http://127.0.0.1:8107"}]
    assert {
        "/",
        "/health",
        "/ready",
        "/version",
        "/internal/v1/auth/service-claim",
        "/internal/v1/auth/service-claim/active",
        "/internal/v1/auth/service-token-runtime",
    }.issubset(contract["paths"])
    assert not any(path.startswith("/api/") for path in contract["paths"])


def test_database_boundary_is_reserved_for_s08_bootstrap() -> None:
    database_root = ROOT / "database/nex-eos"

    assert (database_root / "README.md").is_file()
    assert (
        database_root / "migrations" / "2500_eos_schema_migrations_baseline.sql"
    ).is_file()
