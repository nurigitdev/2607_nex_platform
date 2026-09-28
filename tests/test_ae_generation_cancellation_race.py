from __future__ import annotations

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_ae_api.async_generation import build_async_generation_projection
from nex_ae_api.chat import ChatInteractionStore, register_chat_routes
from nex_ae_api.cx_async_generation_client import CxAsyncGenerationClientError
from nex_ae_api.generation_lifecycle import (
    AE_GENERATION_CANCELLATION_ORCHESTRATION_SCHEMA_VERSION,
    AeGenerationLifecycleError,
    orchestrate_generation_cancellation,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_user_token


def _job(status: str, *, retryable: bool = True) -> dict[str, Any]:
    error = None
    if status in {"FAILED", "CANCELLED"}:
        error = {
            "error_code": f"cx.generation.{status.lower()}",
            "retryable": retryable,
            "dead_lettered": status == "FAILED" and not retryable,
        }
    return {
        "job_id": "job-cancel-race",
        "cx_generation_id": "generation-cancel-race",
        "status": status,
        "attempt_count": 1 if status != "QUEUED" else 0,
        "max_attempts": 3,
        "retryable": retryable,
        "links": {
            "generation": "/api/v1/generations/generation-cancel-race",
            "async_job": "/api/v1/generation-jobs/job-cancel-race",
        },
        "error": error,
    }


def _record(status: str = "QUEUED", *, retryable: bool = True) -> dict[str, Any]:
    projection = build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": _job(status, retryable=retryable),
            "generation": None,
        }
    )
    return {
        "interaction_id": "cancel-race",
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "owner_user_id": "user-a",
        "status": "PENDING",
        "generation": {"async_generation": projection},
    }


def _handoff() -> dict[str, Any]:
    text = "private completed answer"
    encoded = text.encode("utf-8")
    return {
        "handoff_schema_version": "cx_generation_handoff.v1",
        "handoff_status": "READY",
        "next_action": "PRESENT_GENERATION_TO_OWNER",
        "job": _job("SUCCEEDED"),
        "generation": {
            "cx_generation_id": "generation-cancel-race",
            "status": "COMPLETED",
        },
        "content": {
            "cx_generation_id": "generation-cancel-race",
            "content_type": "text/plain",
            "content": text,
            "content_sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
            "owner_scope_enforced": True,
        },
        "owner_scope_enforced": True,
    }


class RaceClient:
    def __init__(self, outcome: str = "CANCELLED") -> None:
        self.outcome = outcome
        self.calls: list[str] = []

    def cancel_job(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("cancel")
        if self.outcome in {"SUCCEEDED", "RUNNING"}:
            raise CxAsyncGenerationClientError(
                409,
                "job.transition_invalid",
                "job became terminal",
            )
        if self.outcome == "UNAVAILABLE":
            raise CxAsyncGenerationClientError(
                503,
                "ae.cx_async_generation.unavailable",
                "unavailable",
                True,
            )
        if self.outcome == "INVALID":
            return _job("CANCELLED") | {"cx_generation_id": "other"}
        return _job("CANCELLED")

    def get_job(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("job")
        return _job(self.outcome)

    def get_handoff(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("handoff")
        return _handoff()


def test_cancellation_succeeds_and_is_idempotent() -> None:
    client = RaceClient()
    result = orchestrate_generation_cancellation(
        _record(), client=client, request_id="request", trace_id="a" * 32
    )
    replay = orchestrate_generation_cancellation(
        {**_record(), "generation": {"async_generation": result["async_generation"]}},
        client=client,
        request_id="request",
        trace_id="a" * 32,
    )

    assert result["cancellation_orchestration_schema_version"] == (
        AE_GENERATION_CANCELLATION_ORCHESTRATION_SCHEMA_VERSION
    )
    assert result["outcome"] == "CANCELLED"
    assert replay["outcome"] == "ALREADY_CANCELLED"
    assert client.calls == ["cancel"]


def test_terminal_completion_wins_cancel_race() -> None:
    client = RaceClient("SUCCEEDED")

    result = orchestrate_generation_cancellation(
        _record(), client=client, request_id="request", trace_id="b" * 32
    )

    assert result["outcome"] == "TERMINAL_STATE_WON"
    assert result["async_generation"]["lifecycle_status"] == "COMPLETED"
    assert "private completed answer" not in str(result)
    assert client.calls == ["cancel", "job", "handoff"]


def test_nonterminal_conflict_and_transport_failure_are_preserved() -> None:
    for outcome, status in (("RUNNING", 409), ("UNAVAILABLE", 503)):
        with pytest.raises(AeGenerationLifecycleError) as exc_info:
            orchestrate_generation_cancellation(
                _record(),
                client=RaceClient(outcome),
                request_id="request",
                trace_id="c" * 32,
            )
        assert exc_info.value.status_code == status


def test_terminal_local_state_and_invalid_contract_are_rejected() -> None:
    completed = _record("SUCCEEDED")
    completed["generation"]["async_generation"].update(
        lifecycle_status="COMPLETED",
        handoff_status="READY",
        next_action="PRESENT_GENERATION_TO_OWNER",
    )
    with pytest.raises(AeGenerationLifecycleError) as terminal:
        orchestrate_generation_cancellation(
            completed,
            client=RaceClient(),
            request_id="request",
            trace_id="d" * 32,
        )
    with pytest.raises(AeGenerationLifecycleError) as invalid:
        orchestrate_generation_cancellation(
            _record(),
            client=RaceClient("INVALID"),
            request_id="request",
            trace_id="d" * 32,
        )
    assert terminal.value.status_code == 409
    assert invalid.value.status_code == 422


class _UnusedClient:
    def create_generation(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("not expected")

    def create_retrieval_context(
        self, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        raise AssertionError("not expected")


def _headers() -> dict[str, str]:
    token = issue_mock_user_token(tenant_id="tenant-a", user_id="user-a")
    return {"Authorization": f"Bearer {token.access_token}"}


def test_cancel_route_persists_terminal_race_winner() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    store.save(_record())
    async_client = RaceClient("SUCCEEDED")
    register_chat_routes(
        app,
        store=store,
        cx_client=_UnusedClient(),
        cx_async_client=async_client,
        retrieval_client=_UnusedClient(),
    )

    response = TestClient(app).post(
        "/api/v1/chat/interactions/cancel-race/cancel",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert store.get("cancel-race")["cx_status"] == "SUCCEEDED"
    assert "private completed answer" not in response.text
