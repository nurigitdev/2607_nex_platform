from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nex_mo.catalog_lifecycle_api import register_catalog_lifecycle_routes
from nex_mo.catalog_lifecycle_repository import (
    CatalogLifecycleRepositoryError,
    InMemoryCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_runtime import (
    CatalogLifecycleRuntimeError,
    build_catalog_lifecycle_service,
)
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService
from nex_mo.main import CATALOG_LIFECYCLE, app as main_app
from nex_mo.provider_auth import authenticated_mo_service_actor
from nex_runtime import issue_mock_service_token
import run_mo_catalog_lifecycle_api as runner


NOW = "2026-10-01T03:00:00Z"


def auth_headers(
    *, service_id: str = "nex-ag", audience: str = "nex-mo"
) -> dict[str, str]:
    token = issue_mock_service_token(service_id=service_id, audience=audience)
    return {"Authorization": f"Bearer {token.access_token}"}


def build_app() -> tuple[FastAPI, InMemoryCatalogLifecycleRepository]:
    repository = InMemoryCatalogLifecycleRepository()
    identifiers = iter(("candidate", "switch", "rollback"))
    service = CatalogLifecycleService(
        repository,
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )
    service.ensure_bootstrap()
    app = FastAPI()
    register_catalog_lifecycle_routes(app, service=service)
    return app, repository


def candidate_payload() -> dict[str, object]:
    return {
        "provider_capability": "generation",
        "model_name": "Generation Candidate",
        "model_revision": "candidate-v1",
        "deployment_id": "candidate-deployment",
        "runtime_profile": "generation-candidate",
        "precision": "BF16",
        "provider_type": "openai-compatible",
        "supports_response_formats": ["text", "json_object"],
        "max_input_tokens": 8192,
        "max_output_tokens": 1024,
    }


def test_api_requires_valid_service_claim() -> None:
    app, _ = build_app()
    client = TestClient(app)
    missing = client.get("/api/v1/model-catalog")
    wrong_audience = client.get(
        "/api/v1/provider-alias-bindings",
        headers=auth_headers(audience="nex-cx"),
    )

    assert missing.status_code == 401
    assert missing.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert wrong_audience.status_code == 401
    assert wrong_audience.json()["error_code"] == "TOKEN_AUDIENCE_INVALID"
    with pytest.raises(ValueError, match="validated"):
        authenticated_mo_service_actor(None)


def test_api_catalog_activation_and_rollback_workflow_is_revisioned() -> None:
    app, repository = build_app()
    client = TestClient(app)
    headers = auth_headers()
    initial = client.get("/api/v1/model-catalog", headers=headers)
    registered = client.post(
        "/api/v1/model-catalog",
        json=candidate_payload(),
        headers=headers,
    )
    catalog_id = registered.json()["catalog_id"]
    activated_catalog = client.post(
        f"/api/v1/model-catalog/{catalog_id}/transitions",
        json={"expected_revision": 1, "target_state": "ACTIVE"},
        headers=headers,
    )
    original = next(
        item
        for item in client.get(
            "/api/v1/provider-alias-bindings?state=ACTIVE",
            headers=headers,
        ).json()["data"]
        if item["provider_capability"] == "generation"
    )
    switched = client.post(
        "/api/v1/provider-alias-bindings/activate",
        json={
            "alias": original["alias"],
            "provider_capability": "generation",
            "catalog_id": catalog_id,
            "expected_binding_revision": 1,
            "change_reason": "Promote candidate",
            "changed_by": "spoofed-actor",
        },
        headers=headers,
    )
    rolled_back = client.post(
        "/api/v1/provider-alias-bindings/rollback",
        json={
            "alias": original["alias"],
            "provider_capability": "generation",
            "expected_binding_revision": 2,
            "change_reason": "Candidate regression",
        },
        headers=headers,
    )

    assert initial.status_code == 200
    assert len(initial.json()["data"]) == 3
    assert registered.status_code == 201
    assert activated_catalog.status_code == 200
    assert activated_catalog.json()["revision"] == 2
    assert switched.status_code == 200
    assert switched.json()["binding_revision"] == 2
    assert rolled_back.status_code == 200
    assert rolled_back.json()["binding_revision"] == 3
    history = repository.list_alias_bindings(
        alias=original["alias"],
        capability="generation",
    )
    assert [item.binding_state for item in history] == [
        "SUPERSEDED",
        "ROLLED_BACK",
        "ACTIVE",
    ]
    assert history[1].changed_by == "service:nex-ag"
    serialized = json.dumps(rolled_back.json())
    assert "changed_by" not in serialized
    assert "spoofed-actor" not in serialized


def test_api_reads_filters_and_maps_safe_errors(monkeypatch) -> None:
    app, repository = build_app()
    client = TestClient(app)
    headers = auth_headers()
    detail = client.get(
        "/api/v1/model-catalog/catalog:missing",
        headers=headers,
    )
    invalid_filter = client.get(
        "/api/v1/model-catalog?capability=other",
        headers=headers,
    )
    malformed = client.post(
        "/api/v1/model-catalog",
        json={"supports_response_formats": "text"},
        headers=headers,
    )
    malformed_integer = client.post(
        "/api/v1/model-catalog",
        json={**candidate_payload(), "max_input_tokens": True},
        headers=headers,
    )
    malformed_dimensions = client.post(
        "/api/v1/model-catalog",
        json={**candidate_payload(), "embedding_dimensions": "bad"},
        headers=headers,
    )
    missing_string = client.post(
        "/api/v1/model-catalog",
        json={**candidate_payload(), "model_name": ""},
        headers=headers,
    )

    assert detail.status_code == 404
    assert detail.json()["error_code"] == "MO_CATALOG_NOT_FOUND"
    assert invalid_filter.status_code == 422
    assert malformed.status_code == 422
    assert malformed_integer.status_code == 422
    assert malformed_dimensions.status_code == 422
    assert missing_string.status_code == 422
    assert all("invalid" in response.json()["detail"].lower() for response in (
        malformed,
        malformed_integer,
        malformed_dimensions,
        missing_string,
    ))

    def unavailable(*args, **kwargs):
        raise CatalogLifecycleRepositoryError(
            "mo.catalog_persistence_unavailable",
            "private database failure",
        )

    monkeypatch.setattr(repository, "list_catalog_entries", unavailable)
    failed = client.get("/api/v1/model-catalog", headers=headers)
    assert failed.status_code == 503
    assert failed.json()["error_code"] == "MO_CATALOG_PERSISTENCE_UNAVAILABLE"
    assert "private database failure" not in failed.json()["detail"]


def test_in_memory_repository_validation_and_runtime_selection(monkeypatch) -> None:
    memory = build_catalog_lifecycle_service(SimpleNamespace(mode="memory"))
    assert len(memory.list_catalog_entries()) == 3
    assert len(memory.list_alias_bindings(state="ACTIVE")) == 3

    with pytest.raises(CatalogLifecycleRuntimeError, match="session factory"):
        build_catalog_lifecycle_service(
            SimpleNamespace(mode="postgres", api_session_factory=None)
        )
    postgres_repository = InMemoryCatalogLifecycleRepository()
    monkeypatch.setattr(
        "nex_mo.catalog_lifecycle_runtime.SqlAlchemyCatalogLifecycleRepository",
        lambda session_factory: postgres_repository,
    )
    postgres = build_catalog_lifecycle_service(
        SimpleNamespace(mode="postgres", api_session_factory=object())
    )
    assert len(postgres.list_catalog_entries()) == 3
    with pytest.raises(CatalogLifecycleRuntimeError, match="memory or postgres"):
        build_catalog_lifecycle_service(SimpleNamespace(mode="other"))

    repository = InMemoryCatalogLifecycleRepository()
    with pytest.raises(CatalogLifecycleRepositoryError):
        repository.list_catalog_entries(capability="other")
    with pytest.raises(CatalogLifecycleRepositoryError):
        repository.list_catalog_entries(state="OTHER")
    with pytest.raises(CatalogLifecycleRepositoryError):
        repository.list_alias_bindings(capability="other")
    with pytest.raises(CatalogLifecycleRepositoryError):
        repository.list_alias_bindings(state="OTHER")


def test_main_app_registers_catalog_lifecycle_service() -> None:
    response = TestClient(main_app).get(
        "/api/v1/model-catalog",
        headers=auth_headers(),
    )
    assert response.status_code == 404
    assert main_app.state.catalog_lifecycle_service is CATALOG_LIFECYCLE


def test_api_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_catalog_lifecycle_api()
    assert "catalog_lifecycle_api=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_catalog_lifecycle_api", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "unauthorized=401" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_catalog_lifecycle_api",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
