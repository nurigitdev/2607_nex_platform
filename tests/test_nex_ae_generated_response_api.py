from __future__ import annotations

from typing import Any, Mapping

import pytest
from fastapi.testclient import TestClient

from nex_ae_api.chat import ChatInteractionStore, register_chat_routes
from nex_ae_api.generated_response_api import build_generated_response_owner_view
from nex_ae_api.generated_response_lineage import attach_generated_response_lineage
from nex_ae_api.generated_response_storage import (
    GeneratedResponseStorageError,
    InMemoryGeneratedResponseStorage,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_user_token
from test_nex_ae_generated_response_lineage import sample_bundle, sample_record


def user_headers(tenant_id: str, user_id: str) -> dict[str, str]:
    token = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
    return {"Authorization": f"Bearer {token.access_token}"}


def response_client(
    *,
    with_lineage: bool = True,
    save_content: bool = True,
    storage: Any | None = None,
) -> tuple[TestClient, ChatInteractionStore, Any]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    resolved_storage = storage or InMemoryGeneratedResponseStorage()
    record = sample_record()
    if with_lineage:
        bundle = sample_bundle()
        record = attach_generated_response_lineage(record, bundle["lineage"])
        if save_content:
            resolved_storage.save(bundle["storage_payload"])
    store.save(record)
    register_chat_routes(
        app,
        store=store,
        generated_response_storage=resolved_storage,
    )
    return TestClient(app), store, resolved_storage


def test_owner_response_route_returns_verified_content_without_storage_ref() -> None:
    client, _, storage = response_client()

    response = client.get(
        f"/api/v1/chat/interactions/{sample_record()['interaction_id']}/response",
        headers=user_headers("tenant-a", "user-a"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_schema_version"] == "ae_generated_response.v1"
    assert body["content"] == "Grounded answer with citation [1]."
    assert body["lineage"]["citation_workflow_status"] == "VALIDATED"
    assert body["owner_scope_enforced"] is True
    assert "storage_ref" not in body["lineage"]
    assert "ae://chat-responses/" not in response.text
    assert client.app.state.ae_generated_response_storage is storage


def test_response_route_hides_missing_and_cross_owner_interactions() -> None:
    client, _, _ = response_client()
    interaction_id = sample_record()["interaction_id"]

    other = client.get(
        f"/api/v1/chat/interactions/{interaction_id}/response",
        headers=user_headers("tenant-a", "user-b"),
    )
    missing = client.get(
        "/api/v1/chat/interactions/missing/response",
        headers=user_headers("tenant-a", "user-a"),
    )
    unauthenticated = client.get(
        f"/api/v1/chat/interactions/{interaction_id}/response"
    )

    assert other.status_code == missing.status_code == 404
    assert other.json()["error_code"] == missing.json()["error_code"]
    assert unauthenticated.status_code == 401


def test_response_route_reports_not_ready_and_missing_private_content() -> None:
    interaction_id = sample_record()["interaction_id"]
    pending_client, _, _ = response_client(with_lineage=False)
    missing_client, _, _ = response_client(save_content=False)

    pending = pending_client.get(
        f"/api/v1/chat/interactions/{interaction_id}/response",
        headers=user_headers("tenant-a", "user-a"),
    )
    missing = missing_client.get(
        f"/api/v1/chat/interactions/{interaction_id}/response",
        headers=user_headers("tenant-a", "user-a"),
    )

    assert pending.status_code == 409
    assert pending.json()["error_code"] == "ae.generated_response_not_ready"
    assert pending.json()["retryable"] is True
    assert missing.status_code == 503
    assert missing.json()["error_code"] == (
        "ae.generated_response_content_unavailable"
    )


def test_response_route_fails_closed_for_tampering_and_lineage_drift() -> None:
    client, store, storage = response_client()
    interaction_id = sample_record()["interaction_id"]
    storage_ref = next(iter(storage.payloads))
    storage.payloads[storage_ref] = b"tampered"
    tampered = client.get(
        f"/api/v1/chat/interactions/{interaction_id}/response",
        headers=user_headers("tenant-a", "user-a"),
    )
    assert tampered.status_code == 503
    assert tampered.json()["error_code"] == "ae.generated_response_integrity_failed"

    record = store.get(interaction_id)
    record["generation"]["generated_response"]["interaction_id"] = "different"
    drift = client.get(
        f"/api/v1/chat/interactions/{interaction_id}/response",
        headers=user_headers("tenant-a", "user-a"),
    )
    assert drift.status_code == 503
    assert drift.json()["error_code"] == "ae.generated_response_lineage_invalid"


class UnavailableStorage:
    def load(self, metadata: Mapping[str, Any]) -> str | None:
        raise GeneratedResponseStorageError(
            error_code="ae.generated_response_storage_unavailable",
            detail="AE generated response storage is unavailable.",
            retryable=True,
        )


class WrongContentStorage:
    def load(self, metadata: Mapping[str, Any]) -> str | None:
        return "wrong content"


@pytest.mark.parametrize(
    ("storage", "error_code"),
    [
        (UnavailableStorage(), "ae.generated_response_storage_unavailable"),
        (WrongContentStorage(), "ae.generated_response_integrity_failed"),
    ],
)
def test_response_route_maps_storage_and_owner_view_failures(
    storage: Any, error_code: str
) -> None:
    client, _, _ = response_client(storage=storage, save_content=False)
    response = client.get(
        f"/api/v1/chat/interactions/{sample_record()['interaction_id']}/response",
        headers=user_headers("tenant-a", "user-a"),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == error_code


def test_owner_view_validates_record_content_type_and_integrity() -> None:
    bundle = sample_bundle()
    lineage = bundle["lineage"]
    content = bundle["storage_payload"]["content"]

    view = build_generated_response_owner_view(sample_record(), lineage, content)
    assert view["lineage"] == lineage

    with pytest.raises(ValueError, match="lineage"):
        build_generated_response_owner_view(
            {**sample_record(), "interaction_id": "different"}, lineage, content
        )
    with pytest.raises(ValueError, match="content"):
        build_generated_response_owner_view(sample_record(), lineage, object())
    with pytest.raises(ValueError, match="integrity"):
        build_generated_response_owner_view(sample_record(), lineage, "different")
