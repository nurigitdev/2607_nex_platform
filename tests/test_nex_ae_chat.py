from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

import nex_ae_api.chat as ae_chat
from nex_ae_api.chat import (
    ChatInteractionError,
    ChatInteractionStore,
    HttpCxGenerationClient,
    build_chat_interaction_record,
    build_cx_generation_payload,
    register_chat_routes,
    user_message_from_payload,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


class FakeCxClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "payload": payload,
                "request_id": request_id,
                "trace_id": trace_id,
            }
        )
        return {
            "cx_generation_id": "cx-gen-001",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": payload["provider_capability"],
            "mo_generation_id": "mo-gen-001",
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "Mock answer.",
            },
            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        }


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "0189f0ff-8f22-4f72-9b47-b481dc21bb21",
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    }


def build_test_client() -> tuple[TestClient, FakeCxClient, ChatInteractionStore]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    cx_client = FakeCxClient()
    register_chat_routes(app, store=store, cx_client=cx_client)
    return TestClient(app), cx_client, store


def test_build_cx_generation_payload_uses_user_message_hash() -> None:
    payload = build_cx_generation_payload(
        {"user_message": "  summarize this document  "},
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert payload["alias"] == "general-llm-default"
    assert payload["messages"] == [{"role": "user", "content": "summarize this document"}]
    assert len(payload["metadata"]["user_message_hash"]) == 64


def test_user_message_from_payload_rejects_empty_message() -> None:
    try:
        user_message_from_payload({"user_message": " "})
    except ChatInteractionError as exc:
        assert exc.status_code == 400
        assert exc.error_code == "ae.chat_request_invalid"
    else:
        raise AssertionError("expected ChatInteractionError")


def test_chat_interaction_endpoint_requires_service_claim() -> None:
    client, _, _ = build_test_client()

    response = client.post("/api/v1/chat/interactions", json={"user_message": "hello"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_chat_interaction_endpoint_calls_cx_and_stores_record() -> None:
    client, cx_client, store = build_test_client()

    response = client.post(
        "/api/v1/chat/interactions",
        json={"user_message": "Summarize the selected evidence."},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["cx_generation_id"] == "cx-gen-001"
    assert payload["generation"]["output_preview"] == "Mock answer."
    assert "Summarize the selected evidence." not in payload["user_message_hash"]
    assert store.get(payload["interaction_id"]) == payload
    assert cx_client.calls[0]["payload"]["messages"][0]["content"] == (
        "Summarize the selected evidence."
    )


def test_chat_interaction_can_be_read_back() -> None:
    client, _, _ = build_test_client()
    created = client.post(
        "/api/v1/chat/interactions",
        json={"user_message": "hello"},
        headers=auth_headers(),
    ).json()

    response = client.get(
        f"/api/v1/chat/interactions/{created['interaction_id']}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["interaction_id"] == created["interaction_id"]


def test_chat_interaction_read_requires_auth() -> None:
    client, _, _ = build_test_client()

    response = client.get("/api/v1/chat/interactions/unknown")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_chat_interaction_read_returns_not_found() -> None:
    client, _, _ = build_test_client()

    response = client.get(
        "/api/v1/chat/interactions/missing",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "ae.chat_interaction_not_found"


def test_chat_interaction_endpoint_rejects_bad_generation_object() -> None:
    client, _, _ = build_test_client()

    response = client.post(
        "/api/v1/chat/interactions",
        json={"user_message": "hello", "generation": "bad"},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ae.chat_request_invalid"


def test_build_chat_interaction_record_maps_cx_metadata() -> None:
    record = build_chat_interaction_record(
        source_payload={"user_message": "hello"},
        cx_payload={
            "client_request_id": "interaction-001",
            "metadata": {
                "chat_document_id": "chat-001",
                "user_message_hash": "a" * 64,
            },
        },
        cx_record={
            "cx_generation_id": "cx-gen-001",
            "status": "COMPLETED",
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "mo_generation_id": "mo-gen-001",
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "answer",
            },
            "usage": {},
        },
        request_id="req",
        trace_id="trace",
    )

    assert record["interaction_id"] == "interaction-001"
    assert record["generation"]["mo_generation_id"] == "mo-gen-001"


def test_http_cx_generation_client_posts_with_mock_token(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return httpx.Response(200, json={"cx_generation_id": "cx-gen-001"})

    monkeypatch.setattr(ae_chat.httpx, "post", fake_post)

    response = HttpCxGenerationClient(base_url="http://cx.test").create_generation(
        {"prompt": "hello"},
        request_id="req-1",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert response["cx_generation_id"] == "cx-gen-001"
    assert calls[0]["args"] == ("http://cx.test/api/v1/generations",)
    assert calls[0]["kwargs"]["headers"]["X-Service-ID"] == "nex-ae-api"


def test_http_cx_generation_client_maps_problem_response(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(
            422,
            json={
                "error_code": "cx.provider_field_forbidden",
                "detail": "Provider field leaked.",
                "retryable": False,
            },
        )

    monkeypatch.setattr(ae_chat.httpx, "post", fake_post)

    try:
        HttpCxGenerationClient(base_url="http://cx.test").create_generation(
            {"prompt": "hello"},
            request_id="req-1",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )
    except ChatInteractionError as exc:
        assert exc.status_code == 422
        assert exc.error_code == "cx.provider_field_forbidden"
    else:
        raise AssertionError("expected ChatInteractionError")


def test_http_cx_generation_client_handles_non_object_error(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(503, json=["bad"])

    monkeypatch.setattr(ae_chat.httpx, "post", fake_post)

    try:
        HttpCxGenerationClient(base_url="http://cx.test").create_generation(
            {"prompt": "hello"},
            request_id="req-1",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )
    except ChatInteractionError as exc:
        assert exc.error_code == "cx.request_failed"
    else:
        raise AssertionError("expected ChatInteractionError")
