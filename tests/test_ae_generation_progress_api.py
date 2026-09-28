from __future__ import annotations

import hashlib
from typing import Any

from fastapi.testclient import TestClient

from nex_ae_api.async_generation import build_async_generation_projection
from nex_ae_api.chat import ChatInteractionStore, register_chat_routes
from nex_ae_api.cx_async_generation_client import CxAsyncGenerationClientError
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_user_token


class _UnusedClient:
    def create_generation(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("synchronous generation is not expected")

    def create_retrieval_context(
        self, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        raise AssertionError("retrieval is not expected")


class ProgressClient:
    def __init__(self) -> None:
        self.job_status = "RUNNING"
        self.error: Exception | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_job(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("job", {"job_id": job_id, **kwargs}))
        if self.error is not None:
            raise self.error
        return _job(self.job_status)

    def get_handoff(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("handoff", {"job_id": job_id, **kwargs}))
        text = "private generated answer"
        encoded = text.encode("utf-8")
        return {
            "handoff_schema_version": "cx_generation_handoff.v1",
            "handoff_status": "READY",
            "next_action": "PRESENT_GENERATION_TO_OWNER",
            "job": _job("SUCCEEDED"),
            "generation": {
                "cx_generation_id": "generation-progress",
                "status": "COMPLETED",
            },
            "content": {
                "cx_generation_id": "generation-progress",
                "content_type": "text/plain",
                "content": text,
                "content_sha256": hashlib.sha256(encoded).hexdigest(),
                "size_bytes": len(encoded),
                "owner_scope_enforced": True,
            },
            "owner_scope_enforced": True,
        }


def _job(status: str) -> dict[str, Any]:
    return {
        "job_id": "job-progress",
        "cx_generation_id": "generation-progress",
        "status": status,
        "attempt_count": 1 if status != "QUEUED" else 0,
        "max_attempts": 3,
        "retryable": True,
        "links": {
            "generation": "/api/v1/generations/generation-progress",
            "async_job": "/api/v1/generation-jobs/job-progress",
        },
        "error": None,
    }


def _record(*, owner: str = "user-a", status: str = "QUEUED") -> dict[str, Any]:
    projection = build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": _job(status),
            "generation": None,
        }
    )
    return {
        "interaction_id": "interaction-progress",
        "tenant_id": "tenant-a",
        "user_id": owner,
        "owner_user_id": owner,
        "user_message_preview": "private question",
        "status": "PENDING",
        "generation": {"async_generation": projection},
    }


def _headers(*, user_id: str = "user-a") -> dict[str, str]:
    token = issue_mock_user_token(tenant_id="tenant-a", user_id=user_id)
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-progress",
        "traceparent": (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ),
    }


def _client() -> tuple[TestClient, ChatInteractionStore, ProgressClient]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    lifecycle = ProgressClient()
    register_chat_routes(
        app,
        store=store,
        cx_client=_UnusedClient(),
        cx_async_client=lifecycle,
        retrieval_client=_UnusedClient(),
    )
    return TestClient(app), store, lifecycle


def test_owner_reads_progress_and_persists_changed_projection() -> None:
    client, store, lifecycle = _client()
    store.save(_record())

    response = client.get(
        "/api/v1/chat/interactions/interaction-progress/progress",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["progress_schema_version"] == "ae_generation_progress.v1"
    assert body["cx_job_status"] == "RUNNING"
    assert body["cancellable"] is True
    assert store.get("interaction-progress")["cx_status"] == "RUNNING"
    assert lifecycle.calls[0][1]["tenant_id"] == "tenant-a"
    assert lifecycle.calls[0][1]["subject_id"] == "user-a"


def test_progress_converges_terminal_handoff_without_private_content() -> None:
    client, store, lifecycle = _client()
    store.save(_record())
    lifecycle.job_status = "SUCCEEDED"

    response = client.get(
        "/api/v1/chat/interactions/interaction-progress/progress",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["lifecycle_status"] == "COMPLETED"
    assert response.json()["progress_percent"] == 100
    assert "private generated answer" not in response.text
    persisted = store.get("interaction-progress")
    assert persisted["status"] == "COMPLETED"
    assert "private generated answer" not in str(persisted)
    assert [name for name, _ in lifecycle.calls] == ["job", "handoff"]


def test_terminal_progress_uses_local_cache() -> None:
    client, store, lifecycle = _client()
    record = _record(status="SUCCEEDED")
    projection = record["generation"]["async_generation"]
    projection.update(
        lifecycle_status="COMPLETED",
        handoff_status="READY",
        next_action="PRESENT_GENERATION_TO_OWNER",
    )
    store.save(record)

    response = client.get(
        "/api/v1/chat/interactions/interaction-progress/progress",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["terminal"] is True
    assert lifecycle.calls == []


def test_progress_is_hidden_from_another_owner() -> None:
    client, store, lifecycle = _client()
    store.save(_record())

    response = client.get(
        "/api/v1/chat/interactions/interaction-progress/progress",
        headers=_headers(user_id="user-b"),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "ae.chat_interaction_not_found"
    assert lifecycle.calls == []


def test_progress_rejects_missing_sync_and_unauthorized_requests() -> None:
    client, store, _ = _client()
    missing = client.get(
        "/api/v1/chat/interactions/missing/progress", headers=_headers()
    )
    store.save(
        {
            "interaction_id": "sync",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "owner_user_id": "user-a",
            "generation": {"policy": {}},
        }
    )
    synchronous = client.get(
        "/api/v1/chat/interactions/sync/progress", headers=_headers()
    )
    unauthorized = client.get(
        "/api/v1/chat/interactions/interaction-progress/progress"
    )

    assert missing.status_code == 404
    assert synchronous.status_code == 409
    assert unauthorized.status_code == 401


def test_progress_normalizes_cx_failure_without_mutating_record() -> None:
    client, store, lifecycle = _client()
    store.save(_record())
    lifecycle.error = CxAsyncGenerationClientError(
        status_code=503,
        error_code="ae.cx_async_generation.unavailable",
        detail="CX is unavailable.",
        retryable=True,
    )

    response = client.get(
        "/api/v1/chat/interactions/interaction-progress/progress",
        headers=_headers(),
    )

    assert response.status_code == 503
    assert response.json()["retryable"] is True
    assert store.get("interaction-progress")["status"] == "PENDING"
