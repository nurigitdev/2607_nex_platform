from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from nex_ae_api.chat import (
    ChatInteractionStore,
    _attach_async_retry_lineage,
    register_chat_routes,
)
from nex_ae_api.cx_async_generation_client import CxAsyncGenerationClientError
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.workspace import WorkspaceStateStore
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)
from nex_runtime.prompts import PromptRegistryStore


class NoSyncClient:
    def create_generation(self, *args, **kwargs):
        raise AssertionError("sync generation is not expected")


class NoRetrievalClient:
    def create_retrieval_context(self, *args, **kwargs):
        raise AssertionError("retrieval is not expected")


class CancelRetryAsyncClient:
    def __init__(self) -> None:
        self.admissions: list[dict[str, Any]] = []
        self.cancellations: list[dict[str, Any]] = []

    def admit_generation(self, payload, **kwargs):
        sequence = len(self.admissions) + 1
        self.admissions.append({"payload": payload, **kwargs})
        return {
            "admission_status": "ENQUEUED",
            "job": self._job(f"job-{sequence}", f"cx-{sequence}", "QUEUED"),
            "generation": None,
        }

    def cancel_job(self, job_id, **kwargs):
        self.cancellations.append({"job_id": job_id, **kwargs})
        generation_id = "cx-1" if job_id == "job-1" else "cx-2"
        return self._job(job_id, generation_id, "CANCELLED", retryable=True)

    def get_handoff(self, *args, **kwargs):
        raise AssertionError("refresh is not expected")

    def get_job(self, *args, **kwargs):
        raise AssertionError("job poll is not expected")

    @staticmethod
    def _job(job_id, generation_id, status, *, retryable=True):
        error = None
        if status == "CANCELLED":
            error = {
                "error_code": "cx.async_generation.cancelled",
                "retryable": retryable,
                "dead_lettered": False,
            }
        return {
            "async_generation_schema_version": "cx_async_generation_job.v1",
            "job_id": job_id,
            "cx_generation_id": generation_id,
            "status": status,
            "attempt_count": 0,
            "max_attempts": 3,
            "retryable": retryable,
            "available_at": None,
            "created_at": "2026-09-28T00:00:00Z",
            "updated_at": "2026-09-28T00:00:01Z",
            "links": {
                "generation": f"/api/v1/generations/{generation_id}",
                "async_job": f"/api/v1/generation-jobs/{job_id}",
            },
            "error": error,
        }


def _headers(tenant_id="tenant-a", user_id="user-a") -> dict[str, str]:
    token = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-cancel-retry",
        "traceparent": (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ),
    }


def _client():
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    prompts = PromptRegistryStore()
    seed_ae_prompt_registry(prompts)
    store = ChatInteractionStore()
    asynchronous = CancelRetryAsyncClient()
    register_chat_routes(
        app,
        store=store,
        cx_client=NoSyncClient(),
        cx_async_client=asynchronous,
        retrieval_client=NoRetrievalClient(),
        prompt_store=prompts,
    )
    return TestClient(app), store, asynchronous


def _payload(interaction_id: str) -> dict:
    return {
        "interaction_id": interaction_id,
        "user_message": "same private question",
        "generation": {"execution_strategy": "ASYNCHRONOUS"},
    }


def test_owner_can_cancel_pending_interaction_idempotently() -> None:
    client, store, asynchronous = _client()
    admitted = client.post(
        "/api/v1/chat/interactions", json=_payload("parent-1"), headers=_headers()
    )
    assert admitted.status_code == 202

    cancelled = client.post(
        "/api/v1/chat/interactions/parent-1/cancel", headers=_headers()
    )
    replay = client.post(
        "/api/v1/chat/interactions/parent-1/cancel", headers=_headers()
    )

    assert cancelled.status_code == replay.status_code == 200
    assert cancelled.json()["status"] == "FAILED"
    assert cancelled.json()["cx_status"] == "CANCELLED"
    assert store.get("parent-1")["failure"]["raw_error_detail_included"] is False
    assert len(asynchronous.cancellations) == 1
    assert asynchronous.cancellations[0]["tenant_id"] == "tenant-a"
    assert asynchronous.cancellations[0]["subject_id"] == "user-a"


def test_cancel_is_hidden_from_another_owner() -> None:
    client, _, asynchronous = _client()
    client.post(
        "/api/v1/chat/interactions", json=_payload("private-1"), headers=_headers()
    )

    response = client.post(
        "/api/v1/chat/interactions/private-1/cancel",
        headers=_headers(user_id="user-b"),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "ae.chat_interaction_not_found"
    assert asynchronous.cancellations == []


def test_workspace_async_cancel_appends_safe_activity() -> None:
    client, _, _ = _client()
    workspace_store = WorkspaceStateStore()
    workspace = workspace_store.create_workspace(
        payload={
            "workspace_id": "workspace-async-cancel",
            "tenant_id": "tenant-a",
            "owner_user_id": "user-a",
        },
        request_id="request-workspace",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    client.app.state.ae_workspace_store = workspace_store
    request_payload = {
        **_payload("workspace-cancel-1"),
        "workspace_id": workspace["workspace_id"],
    }
    admitted = client.post(
        "/api/v1/chat/interactions", json=request_payload, headers=_headers()
    )
    cancelled = client.post(
        "/api/v1/chat/interactions/workspace-cancel-1/cancel",
        headers=_headers(),
    )

    assert admitted.status_code == 202
    assert cancelled.status_code == 200
    activities = workspace_store.list_activities(workspace["workspace_id"])
    assert activities[-1]["activity_type"] == "chat.async.cancelled"
    assert activities[-1]["metadata"]["async_job_status"] == "CANCELLED"
    assert "same private question" not in str(activities)


def test_retry_requires_matching_input_and_new_interaction_then_preserves_lineage() -> None:
    client, store, asynchronous = _client()
    client.post(
        "/api/v1/chat/interactions", json=_payload("parent-1"), headers=_headers()
    )
    client.post(
        "/api/v1/chat/interactions/parent-1/cancel", headers=_headers()
    )

    mismatch = client.post(
        "/api/v1/chat/interactions/parent-1/retry",
        json={**_payload("retry-bad"), "user_message": "different"},
        headers=_headers(),
    )
    same_id = client.post(
        "/api/v1/chat/interactions/parent-1/retry",
        json=_payload("parent-1"),
        headers=_headers(),
    )
    retried = client.post(
        "/api/v1/chat/interactions/parent-1/retry",
        json=_payload("retry-1"),
        headers=_headers(),
    )
    replay = client.post(
        "/api/v1/chat/interactions/parent-1/retry",
        json=_payload("retry-1"),
        headers=_headers(),
    )

    assert mismatch.status_code == 409
    assert same_id.status_code == 400
    assert retried.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == retried.json()
    body = retried.json()
    lineage = body["generation"]["retry_lineage"]
    assert lineage == {
        "retry_lineage_schema_version": "ae_async_generation_retry_lineage.v1",
        "parent_interaction_id": "parent-1",
        "parent_job_id": "job-1",
        "parent_cx_generation_id": "cx-1",
        "parent_response_id": None,
        "raw_input_included": False,
    }
    assert store.get("retry-1")["generation"]["retry_lineage"] == lineage
    assert len(asynchronous.admissions) == 2


def test_retry_rejects_pending_non_retryable_and_bad_generation() -> None:
    client, store, _ = _client()
    client.post(
        "/api/v1/chat/interactions", json=_payload("pending-1"), headers=_headers()
    )
    pending = client.post(
        "/api/v1/chat/interactions/pending-1/retry",
        json=_payload("retry-pending"),
        headers=_headers(),
    )
    assert pending.status_code == 409

    record = store.get("pending-1")
    projection = record["generation"]["async_generation"]
    projection.update(
        lifecycle_status="BLOCKED",
        cx_job_status="FAILED",
        retryable=False,
        next_action="RETRY_OR_REVIEW_GENERATION",
    )
    store.save(record)
    non_retryable = client.post(
        "/api/v1/chat/interactions/pending-1/retry",
        json=_payload("retry-no"),
        headers=_headers(),
    )
    assert non_retryable.status_code == 409

    projection["retryable"] = True
    store.save(record)
    bad_generation = client.post(
        "/api/v1/chat/interactions/pending-1/retry",
        json={
            "interaction_id": "retry-invalid",
            "user_message": "same private question",
            "generation": "bad",
        },
        headers=_headers(),
    )
    assert bad_generation.status_code == 400


def test_completed_and_failed_interactions_are_not_cancellable() -> None:
    client, store, asynchronous = _client()
    client.post(
        "/api/v1/chat/interactions", json=_payload("terminal-1"), headers=_headers()
    )
    record = store.get("terminal-1")
    projection = record["generation"]["async_generation"]
    projection.update(
        lifecycle_status="COMPLETED",
        cx_job_status="SUCCEEDED",
        handoff_status="READY",
        next_action="PRESENT_GENERATION_TO_OWNER",
    )
    store.save(record)
    completed = client.post(
        "/api/v1/chat/interactions/terminal-1/cancel", headers=_headers()
    )
    assert completed.status_code == 409

    projection.update(
        lifecycle_status="BLOCKED",
        cx_job_status="FAILED",
        handoff_status="BLOCKED",
        next_action="RETRY_OR_REVIEW_GENERATION",
    )
    store.save(record)
    blocked = client.post(
        "/api/v1/chat/interactions/terminal-1/cancel", headers=_headers()
    )
    assert blocked.status_code == 409
    assert asynchronous.cancellations == []


def test_cancel_normalizes_transport_and_contract_failures() -> None:
    client, store, asynchronous = _client()
    client.post(
        "/api/v1/chat/interactions", json=_payload("errors-1"), headers=_headers()
    )

    def unavailable(*args, **kwargs):
        raise CxAsyncGenerationClientError(
            503, "cx.async_generation.unavailable", "unavailable", True
        )

    asynchronous.cancel_job = unavailable
    transport = client.post(
        "/api/v1/chat/interactions/errors-1/cancel", headers=_headers()
    )
    assert transport.status_code == 503
    assert transport.json()["retryable"] is True

    asynchronous.cancel_job = lambda *args, **kwargs: asynchronous._job(
        "job-1", "other-generation", "CANCELLED"
    )
    contract = client.post(
        "/api/v1/chat/interactions/errors-1/cancel", headers=_headers()
    )
    assert contract.status_code == 422
    assert contract.json()["error_code"] == "ae.async_generation.contract_invalid"
    assert store.get("errors-1")["status"] == "PENDING"


def test_cancel_and_retry_require_authorization() -> None:
    client, _, _ = _client()
    cancel = client.post("/api/v1/chat/interactions/missing/cancel")
    retry = client.post(
        "/api/v1/chat/interactions/missing/retry", json=_payload("new")
    )
    assert cancel.status_code == retry.status_code == 401


def test_retry_lineage_helper_preserves_error_and_unrelated_responses() -> None:
    store = ChatInteractionStore()
    parent = {"interaction_id": "parent"}
    projection = {"job_id": "job", "cx_generation_id": "generation"}
    failure = JSONResponse(status_code=409, content={"error_code": "conflict"})
    unrelated = {"generation": {"policy": {}}}
    marker = object()

    assert _attach_async_retry_lineage(
        failure, chat_store=store, parent=parent, projection=projection
    ) is failure
    assert _attach_async_retry_lineage(
        unrelated, chat_store=store, parent=parent, projection=projection
    ) == unrelated
    assert _attach_async_retry_lineage(
        marker, chat_store=store, parent=parent, projection=projection
    ) is marker
