from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import nex_runtime.database as runtime_database
import pytest
import run_all_services
import run_service
import run_tiered_quality_gate
from fastapi.testclient import TestClient
from nex_oa.production_token_profiles import TOKEN_AUDIENCES
from nex_oa.service_principal_boundary import KNOWN_SERVICE_IDS as OA_SERVICE_IDS
from nex_runtime import SERVICE_RUNTIME_OPERATION_SPECS, SERVICE_SPECS
from nex_runtime.auth import KNOWN_SERVICE_IDS
from nex_runtime.background_process import background_process_metadata
from nex_runtime.database import service_database_env_prefix
from nex_runtime.deployment_artifacts import build_current_deployment_artifact_catalog
from nex_runtime.postgres_targets import CURRENT_POSTGRES_TEST_TARGETS
from nex_runtime.process_manifest import build_current_platform_runtime_manifest
from nex_runtime.service_endpoints import (
    CURRENT_SERVICE_ENDPOINTS,
    resolve_service_endpoint,
)
from nex_runtime.service_logs import SERVICE_IDS as SERVICE_LOG_IDS
from nex_runtime.signed_token_verifier import SIGNED_TOKEN_AUDIENCES
from nex_runtime.worker_heartbeats import SERVICE_IDS as HEARTBEAT_SERVICE_IDS
from nex_wa import WaConfigurationError, load_wa_settings
from nex_wa.app import CONTRACT_CATALOG_VERSION, SERVICE_SPEC, create_wa_app

ROOT = Path(__file__).parents[1]
PLATFORM_BACKEND_IDS = {
    "nex-oa",
    "nex-ag",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-wc",
    "nex-eos",
    "nex-wa",
}


class FakeCursor:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        assert sql.lower() == "select current_database(), current_user"

    def fetchone(self) -> tuple[str, str]:
        return ("nex_wa_test", "nex_wa_user")


class FakeConnection:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor()


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "NEX_WA_SERVICE_ID": "nex-wa",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p9-s01",
        "NEX_BUILD_SHA": "p9s01test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    values.update(overrides)
    return values


def test_settings_are_fail_closed_and_public_projection_is_safe() -> None:
    settings = load_wa_settings(_environment())

    assert settings.public_projection() == {
        "service_id": "nex-wa",
        "profile": "test",
        "version": "2.1.0-p9-s01",
        "build_sha": "p9s01test",
        "database_env": "NEX_WA_DATABASE_URL",
    }


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("NEX_WA_SERVICE_ID", "nex-eos", "must be nex-wa"),
        ("NEX_PROFILE", "unknown", "unsupported WA runtime profile"),
        ("NEX_PROFILE", " test", "outer whitespace"),
        ("NEX_VERSION", "bad version", "invalid format"),
        ("NEX_BUILD_SHA", "", "non-empty string"),
    ],
)
def test_settings_reject_invalid_startup_values(
    name: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(WaConfigurationError, match=message):
        load_wa_settings(_environment(**{name: value}))


def test_settings_reject_non_string_identity_value() -> None:
    environment: dict[str, object] = dict(_environment())
    environment["NEX_BUILD_SHA"] = 8

    with pytest.raises(WaConfigurationError, match="non-empty string"):
        load_wa_settings(environment)  # type: ignore[arg-type]


def test_service_shell_has_protected_trust_and_no_domain_routes() -> None:
    app = create_wa_app(environ=_environment())
    client = TestClient(app)

    assert app.title == "NeX Work Asset Service"
    assert app.state.wa_settings.service_id == "nex-wa"
    assert app.state.wa_service_token_admission.expected_audience == "nex-wa"
    assert client.get("/").json()["service_id"] == "nex-wa"
    assert client.get("/health").json()["health_status"] == "HEALTHY"
    assert client.get("/version").json()["contract_catalog_version"] == (
        CONTRACT_CATALOG_VERSION
    )
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
    assert not any("work-evidence" in path or "work-assets" in path for path in routes)


def test_readiness_uses_exact_wa_database_environment_without_leaking_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_connect(database_url: str, connect_timeout: int) -> FakeConnection:
        calls.append((database_url, connect_timeout))
        return FakeConnection()

    database_url = "postgresql://nex_wa_user:private@localhost/nex_wa_test"
    monkeypatch.setattr(runtime_database.psycopg, "connect", fake_connect)
    response = TestClient(
        create_wa_app(
            environ=_environment(NEX_WA_DATABASE_URL=database_url),
            persistence_builder=lambda **_kwargs: SimpleNamespace(
                work_evidence_repository=None,
                work_asset_repository=None,
                migration_readiness=lambda: {
                    "name": "wa_migrations",
                    "ok": True,
                }
            ),  # type: ignore[arg-type]
        )
    ).get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"][0]["database_name"] == "nex_wa_test"
    assert response.json()["checks"][0]["database_user"] == "nex_wa_user"
    assert "private" not in response.text
    assert calls == [(database_url, 2)]


def test_all_first_class_registries_include_wa_without_partial_registration() -> None:
    target_ids = {target.service_id for target in CURRENT_POSTGRES_TEST_TARGETS}

    assert set(SERVICE_SPECS) == PLATFORM_BACKEND_IDS
    assert set(CURRENT_SERVICE_ENDPOINTS) == PLATFORM_BACKEND_IDS
    assert target_ids == PLATFORM_BACKEND_IDS
    assert set(HEARTBEAT_SERVICE_IDS) == PLATFORM_BACKEND_IDS
    assert set(SERVICE_LOG_IDS) == PLATFORM_BACKEND_IDS
    assert KNOWN_SERVICE_IDS == PLATFORM_BACKEND_IDS
    assert SIGNED_TOKEN_AUDIENCES == PLATFORM_BACKEND_IDS
    assert OA_SERVICE_IDS == PLATFORM_BACKEND_IDS
    assert TOKEN_AUDIENCES == PLATFORM_BACKEND_IDS
    assert "nex-wa" not in SERVICE_RUNTIME_OPERATION_SPECS


def test_endpoint_database_and_developer_tool_registration_is_exact() -> None:
    endpoint = resolve_service_endpoint("nex-wa", environ={})

    assert SERVICE_SPEC is SERVICE_SPECS["nex-wa"]
    assert SERVICE_SPEC.default_port == 8108
    assert endpoint.environment_name == "NEX_WA_BASE_URL"
    assert endpoint.base_url == "http://127.0.0.1:8108"
    assert service_database_env_prefix("nex-wa") == "NEX_WA"
    assert run_service.SERVICE_MODULES["nex-wa"] == "nex_wa.main:app"
    assert run_all_services.SERVICES[-1] == "nex-wa"
    assert "nex-wa" in run_tiered_quality_gate.SERVICE_PROFILES


def test_runtime_and_deployment_catalog_register_both_wa_processes() -> None:
    manifest = build_current_platform_runtime_manifest(
        environ={}, python_executable="python"
    )
    processes = {process.process_id: process for process in manifest.processes}
    catalog = build_current_deployment_artifact_catalog()
    bindings = {binding.process_id: binding for binding in catalog.process_bindings}

    assert processes["nex-wa-api"].port == 8108
    assert "NEX_WA_DATABASE_URL" in processes["nex-wa-api"].environment_names
    assert processes["nex-wa-evidence-consumer"].owner == "nex-wa"
    assert bindings["nex-wa-api"].artifact_id == "nex-wa-runtime"
    assert bindings["nex-wa-evidence-consumer"].artifact_id == "nex-wa-runtime"
    assert any(item.artifact_id == "nex-wa-runtime" for item in catalog.artifacts)


def test_consumer_process_is_registered_but_domain_processing_is_not_active() -> None:
    metadata = background_process_metadata(
        "nex-wa-evidence-consumer",
        "local_mock",
    )
    consumer = importlib.import_module("nex_wa.consumer")

    assert metadata["service_id"] == "nex-wa"
    assert metadata["work_claiming_enabled"] is False
    assert consumer.package_readiness()["domain_processing_enabled"] is False


def test_repository_configuration_and_oa_constraint_admit_wa() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    quality_gate = (ROOT / "scripts/quality/run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    environment = (ROOT / ".env.example").read_text(encoding="utf-8")
    migration = (
        ROOT / "database/nex-oa/migrations/2517_oa_service_principal_wa.sql"
    ).read_text(encoding="utf-8")

    assert '"services/nex-wa"' in pyproject
    assert "services/nex-wa" in quality_gate
    assert "NEX_WA_BASE_URL=http://127.0.0.1:8108" in environment
    assert "NEX_WA_DATABASE_URL=postgresql://nex_wa_user:" in environment
    assert "NEX_WA_TEST_DATABASE_URL=postgresql://nex_wa_user:" in environment
    assert "'nex-wa'" in migration
    assert "oa_service_principals_service_id_check" in migration
    assert "oa_token_revocations_audience_check" in migration


def test_main_module_exports_executable_app() -> None:
    module = importlib.import_module("nex_wa.main")

    assert module.app.state.wa_settings.service_id == "nex-wa"
    assert module.SERVICE_SPEC is SERVICE_SPEC
