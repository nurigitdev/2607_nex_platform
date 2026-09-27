from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_ae_api.prompt_persistence import (
    PromptRepositoryError,
    SqlAlchemyAePromptRegistryStore,
)
from nex_ae_api.prompts import (
    AE_GENERAL_ANSWER_BINDING,
    DEFAULT_AE_PROMPT_STORE,
    build_default_ae_prompt_store,
    seed_ae_prompt_registry,
)
from nex_ae_api.runtime_policy_api import (
    RuntimePolicyApiError,
    register_runtime_policy_routes,
    resolve_safe_prompt_binding,
)
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)
from nex_runtime.prompts import PromptRegistryStore


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def auth_headers(*, browser: bool = False) -> dict[str, str]:
    issued = (
        issue_mock_user_token(tenant_id="tenant-policy", user_id="user-policy")
        if browser
        else issue_mock_service_token(service_id="nex-ag", audience="nex-ae-api")
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "request-policy-api",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_client(store=None) -> tuple[TestClient, object]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    prompt_store = store or PromptRegistryStore()
    if isinstance(prompt_store, PromptRegistryStore):
        seed_ae_prompt_registry(prompt_store)
    register_runtime_policy_routes(app, store=prompt_store)
    return TestClient(app), prompt_store


def test_policy_catalog_is_protected_and_raw_safe() -> None:
    client, _ = build_client()

    denied = client.get("/api/v1/runtime-policies")
    response = client.get("/api/v1/runtime-policies", headers=auth_headers())

    assert denied.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["runtime_policy_catalog_schema_version"] == (
        "ae_runtime_policy_catalog.v1"
    )
    assert len(body["policies"]) == 6
    assert {item["execution_mode"] for item in body["policies"]} == {
        "GENERAL_ANSWER",
        "GROUNDED_ANSWER",
        "DOCUMENT_SUMMARY",
        "DOCUMENT_GENERATION",
    }
    serialized = str(body)
    assert "content" not in serialized
    assert "api_key" not in serialized
    assert all(item["raw_prompt_included"] is False for item in body["policies"])


def test_policy_resolution_accepts_browser_auth_and_projects_binding_safely() -> None:
    client, _ = build_client()
    private_prompt = "private customer strategy"

    response = client.post(
        "/api/v1/runtime-policies/resolve",
        headers=auth_headers(browser=True),
        json={"user_message": private_prompt},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["compatibility_rule"]["rule_id"] == "ae.general_answer.v1"
    assert body["prompt_binding"]["binding_key"] == AE_GENERAL_ANSWER_BINDING
    assert body["prompt_binding"]["prompt_version"] == "v1"
    assert len(body["prompt_binding"]["content_sha256"]) == 64
    assert body["prompt_binding"]["content_included"] is False
    assert private_prompt not in str(body)


def test_prompt_binding_inspection_is_protected_and_safe() -> None:
    client, _ = build_client()
    route = f"/api/v1/runtime-policies/prompt-bindings/{AE_GENERAL_ANSWER_BINDING}"

    denied = client.get(route)
    response = client.get(route, headers=auth_headers())

    assert denied.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["prompt_binding_projection_schema_version"] == (
        "ae_prompt_binding_projection.v1"
    )
    assert body["content_included"] is False
    assert "content" not in {key for key in body if key != "content_included"}


def test_policy_api_maps_resolution_and_repository_failures() -> None:
    client, store = build_client()
    denied = client.post(
        "/api/v1/runtime-policies/resolve",
        json={"user_message": "hello"},
    )
    invalid = client.post(
        "/api/v1/runtime-policies/resolve",
        headers=auth_headers(),
        json={
            "user_message": "hello",
            "generation": {"provider_url": "http://forbidden"},
        },
    )
    missing = client.get(
        "/api/v1/runtime-policies/prompt-bindings/missing",
        headers=auth_headers(),
    )

    assert denied.status_code == 401
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "ae.provider_runtime_field_forbidden"
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.prompt_binding_not_found"

    class FailingStore:
        def get_binding(self, binding_key):
            raise PromptRepositoryError(
                "ae.prompt_registry_unavailable",
                "AE prompt registry is unavailable.",
                True,
            )

    failing_client, _ = build_client(FailingStore())
    unavailable = failing_client.post(
        "/api/v1/runtime-policies/resolve",
        headers=auth_headers(),
        json={"user_message": "hello"},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True
    assert store.get_binding(AE_GENERAL_ANSWER_BINDING) is not None


def test_safe_binding_rejects_inactive_missing_and_mismatched_versions() -> None:
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    binding = store.get_binding(AE_GENERAL_ANSWER_BINDING)
    version = store.get_template_version(binding["prompt_template_version_id"])

    binding["status"] = "INACTIVE"
    _assert_binding_error(store, "ae.prompt_binding_inactive")

    binding["status"] = "ACTIVE"
    store.template_versions.pop(binding["prompt_template_version_id"])
    _assert_binding_error(store, "ae.prompt_version_not_found")

    store.template_versions[binding["prompt_template_version_id"]] = version
    version["status"] = "INACTIVE"
    _assert_binding_error(store, "ae.prompt_version_inactive")

    version["status"] = "ACTIVE"
    _assert_binding_error(store, "ae.prompt_version_mismatch", prompt_version="v2")


def _assert_binding_error(
    store: PromptRegistryStore,
    expected: str,
    *,
    prompt_version: str | None = None,
) -> None:
    with pytest.raises(RuntimePolicyApiError) as raised:
        resolve_safe_prompt_binding(
            store,
            binding_key=AE_GENERAL_ANSWER_BINDING,
            prompt_version=prompt_version,
        )
    assert raised.value.error_code == expected


def test_default_prompt_store_uses_sql_persistence_and_seeds_registry() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        _create_prompt_schema(connection)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    app.state.nex_persistence = SimpleNamespace(api_session_factory=factory)

    store = build_default_ae_prompt_store(app)

    assert isinstance(store, SqlAlchemyAePromptRegistryStore)
    assert len(store.list_bindings()) == 4
    plain_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    assert build_default_ae_prompt_store(plain_app) is DEFAULT_AE_PROMPT_STORE


def _create_prompt_schema(connection) -> None:
    connection.execute(text("""
        CREATE TABLE ae_prompt_templates (
            prompt_template_id TEXT PRIMARY KEY, service_id TEXT NOT NULL,
            purpose TEXT NOT NULL, name TEXT NOT NULL, owner_domain TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (service_id, purpose, name)
        )
    """))
    connection.execute(text("""
        CREATE TABLE ae_prompt_template_versions (
            prompt_template_version_id TEXT PRIMARY KEY,
            prompt_template_id TEXT NOT NULL, version TEXT NOT NULL,
            role TEXT NOT NULL, segment_order INTEGER NOT NULL,
            content TEXT NOT NULL, content_sha256 TEXT NOT NULL,
            model_capability TEXT NOT NULL, metadata TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE (prompt_template_id, version, role, segment_order)
        )
    """))
    connection.execute(text("""
        CREATE TABLE ae_prompt_bindings (
            prompt_binding_id TEXT PRIMARY KEY, binding_key TEXT NOT NULL UNIQUE,
            prompt_template_version_id TEXT NOT NULL, service_id TEXT NOT NULL,
            purpose TEXT NOT NULL, status TEXT NOT NULL, bound_at TEXT NOT NULL
        )
    """))
    connection.execute(text("""
        CREATE TABLE ae_prompt_render_events (
            prompt_render_event_id TEXT PRIMARY KEY, prompt_binding_id TEXT,
            prompt_template_version_id TEXT, trace_id TEXT NOT NULL,
            request_id TEXT NOT NULL, rendered_prompt_hash TEXT NOT NULL,
            rendered_prompt_preview TEXT, user_prompt_hash TEXT, output_hash TEXT,
            metadata TEXT NOT NULL, created_at TEXT NOT NULL
        )
    """))
