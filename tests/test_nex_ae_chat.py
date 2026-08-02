from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

import nex_ae_api.chat as ae_chat
from nex_ae_api.chat import (
    ChatInteractionError,
    ChatInteractionStore,
    HttpCxGenerationClient,
    attach_retrieval_package_to_generation_payload,
    artifact_actions_for_record,
    artifact_record_from_payload,
    build_chat_artifact_ref,
    build_chat_interaction_record,
    build_cx_generation_payload,
    build_grounded_user_message,
    build_no_answer_chat_interaction_record,
    register_chat_routes,
    retrieval_summary,
    should_use_retrieval,
    user_message_from_payload,
)
from nex_ae_api.retrieval import RetrievalInteractionError
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


class FakeRetrievalClient:
    def __init__(self, *, status: str = "READY") -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status

    def create_retrieval_context(
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
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "b" * 64,
            "status": self.status,
            "purpose": payload["purpose"],
            "evidence_items": [
                {
                    "citation_label": "[1]",
                    "text": "Trace evidence from CX.",
                }
            ]
            if self.status == "READY"
            else [],
            "score_summary": {
                "best_score": 0.9 if self.status == "READY" else 0.0,
                "confidence_bucket": self.status,
            },
            "no_answer_reason": None if self.status == "READY" else "no_terms_matched",
            "warnings": [],
        }


class FailingRetrievalClient:
    def create_retrieval_context(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        raise RetrievalInteractionError(
            status_code=503,
            error_code="cx.retrieval_unavailable",
            detail="CX retrieval unavailable.",
            retryable=True,
        )


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


def build_grounded_test_client(
    retrieval_client: FakeRetrievalClient | FailingRetrievalClient | None = None,
) -> tuple[
    TestClient,
    FakeCxClient,
    FakeRetrievalClient | FailingRetrievalClient,
    ChatInteractionStore,
]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    cx_client = FakeCxClient()
    retrieval = retrieval_client or FakeRetrievalClient()
    register_chat_routes(
        app,
        store=store,
        cx_client=cx_client,
        retrieval_client=retrieval,
    )
    return TestClient(app), cx_client, retrieval, store


def sample_artifact_record(
    *,
    chat_document_id: str = "chat-001",
    interaction_id: str = "interaction-001",
    current_version_id: str | None = "artifact-version-001",
    status: str = "READY",
) -> dict[str, Any]:
    return {
        "artifact_id": "artifact-001",
        "artifact_type": "generated_document",
        "artifact_status": status,
        "current_version_id": current_version_id,
        "chat_document_id": chat_document_id,
        "interaction_id": interaction_id,
        "display_title": "Generated report",
        "target_formats": ["MD", "HTML_PREVIEW"],
        "source_refs": [
            {
                "cx_generation_id": "cx-gen-001",
                "structured_draft_content_hash": "c" * 64,
                "quality_summary": {
                    "citation_status": "VALIDATED",
                    "citation_count": 2,
                    "validation_error_count": 0,
                    "warning_count": 0,
                    "grounding_required": True,
                    "retrieval_package_id": "cx-ret-001",
                    "retrieval_package_hash": "d" * 64,
                    "evidence_ref_count": 2,
                },
            }
        ],
        "versions": [
            {
                "artifact_version_id": "artifact-version-001",
                "source_content_hash": "c" * 64,
            }
        ],
        "files": [
            {
                "artifact_file_id": "artifact-file-001",
                "format": "MD",
            }
        ],
        "links": [
            {
                "artifact_file_id": "artifact-file-001",
                "link_type": "preview",
                "link_route": "/api/v1/artifact-files/artifact-file-001/preview",
            },
            {
                "artifact_file_id": "artifact-file-001",
                "link_type": "download",
                "link_route": "/api/v1/artifact-files/artifact-file-001/download",
            },
        ],
    }


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
    assert payload["artifact_refs"] == []
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


def test_chat_artifact_link_route_attaches_and_lists_refs() -> None:
    client, _, store = build_test_client()
    created = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "interaction-001",
            "chat_document_id": "chat-001",
            "user_message": "hello",
        },
        headers=auth_headers(),
    ).json()

    attached = client.post(
        f"/api/v1/chat/interactions/{created['interaction_id']}/artifact-links",
        json={"artifact": sample_artifact_record()},
        headers=auth_headers(),
    )
    repeated = client.post(
        f"/api/v1/chat/interactions/{created['interaction_id']}/artifact-links",
        json={"artifact": sample_artifact_record()},
        headers=auth_headers(),
    )
    listed = client.get(
        f"/api/v1/chat/interactions/{created['interaction_id']}/artifact-links",
        headers=auth_headers(),
    )

    assert attached.status_code == 200
    assert len(attached.json()["artifact_refs"]) == 1
    assert repeated.status_code == 200
    assert len(repeated.json()["artifact_refs"]) == 1
    assert listed.status_code == 200
    assert listed.json()["artifact_refs"] == attached.json()["artifact_refs"]
    assert store.get(created["interaction_id"])["artifact_refs"] == attached.json()[
        "artifact_refs"
    ]


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


def test_chat_artifact_link_routes_require_auth_and_matching_scope() -> None:
    client, _, _ = build_test_client()
    created = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "interaction-001",
            "chat_document_id": "chat-001",
            "user_message": "hello",
        },
        headers=auth_headers(),
    ).json()

    unauthorized = client.post(
        f"/api/v1/chat/interactions/{created['interaction_id']}/artifact-links",
        json={"artifact": sample_artifact_record()},
    )
    missing = client.post(
        "/api/v1/chat/interactions/missing/artifact-links",
        json={"artifact": sample_artifact_record()},
        headers=auth_headers(),
    )
    missing_list = client.get(
        "/api/v1/chat/interactions/missing/artifact-links",
        headers=auth_headers(),
    )
    bad_chat_document = client.post(
        f"/api/v1/chat/interactions/{created['interaction_id']}/artifact-links",
        json={"artifact": sample_artifact_record(chat_document_id="other-chat")},
        headers=auth_headers(),
    )
    bad_interaction = client.post(
        f"/api/v1/chat/interactions/{created['interaction_id']}/artifact-links",
        json={"artifact": sample_artifact_record(interaction_id="other-interaction")},
        headers=auth_headers(),
    )
    bad_artifact = client.post(
        f"/api/v1/chat/interactions/{created['interaction_id']}/artifact-links",
        json={"artifact": sample_artifact_record(current_version_id=None)},
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ae.chat_interaction_not_found"
    assert missing_list.status_code == 404
    assert bad_chat_document.status_code == 409
    assert bad_chat_document.json()["error_code"] == "ae.artifact_link_scope_mismatch"
    assert bad_interaction.status_code == 409
    assert bad_interaction.json()["error_code"] == "ae.artifact_link_scope_mismatch"
    assert bad_artifact.status_code == 409
    assert bad_artifact.json()["error_code"] == "ae.artifact_link_version_required"


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
    assert record["retrieval"] is None
    assert record["artifact_refs"] == []


def test_build_chat_artifact_ref_maps_artifact_routes_and_actions() -> None:
    artifact_ref = build_chat_artifact_ref(sample_artifact_record())

    assert artifact_ref["artifact_id"] == "artifact-001"
    assert artifact_ref["artifact_version_id"] == "artifact-version-001"
    assert artifact_ref["primary_format"] == "MD"
    assert artifact_ref["available_formats"] == ["MD"]
    assert artifact_ref["preview_route"].endswith("/preview")
    assert artifact_ref["download_routes"] == {
        "MD": "/api/v1/artifact-files/artifact-file-001/download"
    }
    assert artifact_ref["source_generation_id"] == "cx-gen-001"
    assert artifact_ref["source_content_hash"] == "c" * 64
    assert artifact_ref["actions"] == [
        "preview",
        "view_sources",
        "view_lineage",
        "download_md",
    ]
    assert "/data/nex-platform" not in str(artifact_ref)


def test_chat_artifact_ref_guards_missing_version_and_bad_payload() -> None:
    try:
        artifact_record_from_payload({})
    except ChatInteractionError as exc:
        assert exc.error_code == "ae.artifact_record_required"
    else:
        raise AssertionError("expected ChatInteractionError")

    try:
        build_chat_artifact_ref(sample_artifact_record(current_version_id=None))
    except ChatInteractionError as exc:
        assert exc.error_code == "ae.artifact_link_version_required"
    else:
        raise AssertionError("expected ChatInteractionError")

    missing_version = sample_artifact_record(current_version_id="missing-version")
    try:
        build_chat_artifact_ref(missing_version)
    except ChatInteractionError as exc:
        assert exc.error_code == "ae.artifact_link_version_required"
    else:
        raise AssertionError("expected ChatInteractionError")

    bad_record = {**sample_artifact_record(), "target_formats": ["MD"]}
    bad_record["files"] = []
    bad_record["links"] = []
    artifact_ref = build_chat_artifact_ref(bad_record)
    assert artifact_ref["available_formats"] == []
    assert artifact_ref["primary_format"] == "MD"
    assert artifact_ref["preview_route"] is None
    assert artifact_ref["download_routes"] == {}
    assert artifact_actions_for_record(
        {**sample_artifact_record(status="FAILED"), "links": []}
    ) == ["view_sources", "view_lineage", "retry_render"]

    no_targets = {**sample_artifact_record(), "target_formats": [], "files": []}
    try:
        build_chat_artifact_ref(no_targets)
    except ChatInteractionError as exc:
        assert exc.error_code == "ae.artifact_record_invalid"
    else:
        raise AssertionError("expected ChatInteractionError")


def test_should_use_retrieval_handles_disabled_and_invalid_payloads() -> None:
    assert should_use_retrieval({}) is False
    assert should_use_retrieval({"retrieval": {"enabled": False}}) is False
    assert should_use_retrieval({"retrieval": {"enabled": True}}) is True

    try:
        should_use_retrieval({"retrieval": "bad"})
    except ChatInteractionError as exc:
        assert exc.error_code == "ae.chat_request_invalid"
    else:
        raise AssertionError("expected ChatInteractionError")


def test_build_grounded_user_message_formats_evidence() -> None:
    message = build_grounded_user_message(
        "Summarize",
        {
            "evidence_items": [
                {"citation_label": "[1]", "text": "First evidence."},
                {"citation_label": "[2]", "text": "Second evidence."},
            ]
        },
    )

    assert "User request:\nSummarize" in message
    assert "[1] First evidence." in message
    assert "[2] Second evidence." in message


def test_build_grounded_user_message_handles_empty_evidence() -> None:
    assert "No supporting evidence returned." in build_grounded_user_message(
        "Summarize",
        {"evidence_items": []},
    )


def test_attach_retrieval_package_to_generation_payload_adds_metadata() -> None:
    cx_payload = build_cx_generation_payload({"user_message": "hello"}, trace_id="trace")
    updated = attach_retrieval_package_to_generation_payload(
        cx_payload,
        {
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "b" * 64,
            "status": "READY",
            "evidence_items": [{"citation_label": "[1]", "text": "Evidence."}],
        },
    )

    assert updated["metadata"]["retrieval_package_id"] == "cx-ret-001"
    assert updated["metadata"]["retrieval_evidence_count"] == 1
    assert "Supporting evidence" in updated["messages"][0]["content"]


def test_retrieval_summary_maps_package() -> None:
    summary = retrieval_summary(
        {
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "b" * 64,
            "status": "READY",
            "evidence_items": [{"evidence_id": "ev-1"}],
            "score_summary": {"best_score": 0.9, "confidence_bucket": "READY"},
            "warnings": ["w"],
        }
    )

    assert summary["cx_retrieval_package_id"] == "cx-ret-001"
    assert summary["evidence_count"] == 1
    assert summary["warnings"] == ["w"]


def test_build_no_answer_chat_interaction_record_skips_generation() -> None:
    record = build_no_answer_chat_interaction_record(
        source_payload={"user_message": "missing"},
        retrieval_payload={
            "metadata": {
                "ae_retrieval_interaction_id": "ret-001",
                "chat_document_id": "chat-001",
                "user_message_hash": "a" * 64,
            }
        },
        retrieval_package={
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "b" * 64,
            "status": "NO_ANSWER",
            "evidence_items": [],
            "score_summary": {"best_score": 0.0, "confidence_bucket": "NO_ANSWER"},
            "no_answer_reason": "no_terms_matched",
            "warnings": [],
        },
        request_id="req",
        trace_id="trace",
    )

    assert record["status"] == "NO_ANSWER"
    assert record["cx_generation_id"] is None
    assert record["generation"] is None
    assert record["retrieval"]["no_answer_reason"] == "no_terms_matched"


def test_chat_interaction_with_retrieval_calls_cx_retrieval_then_generation() -> None:
    client, cx_client, retrieval_client, store = build_grounded_test_client()

    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "user_message": "Summarize trace evidence.",
            "retrieval": {"purpose": "grounded_answer", "top_k": 1},
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["retrieval"]["cx_retrieval_package_id"] == "cx-ret-001"
    assert retrieval_client.calls[0]["payload"]["purpose"] == "grounded_answer"
    assert cx_client.calls[0]["payload"]["metadata"]["retrieval_package_id"] == "cx-ret-001"
    assert "Trace evidence from CX." in cx_client.calls[0]["payload"]["messages"][0]["content"]
    assert store.get(payload["interaction_id"]) == payload


def test_chat_interaction_with_retrieval_disabled_skips_retrieval() -> None:
    client, cx_client, retrieval_client, _ = build_grounded_test_client()

    response = client.post(
        "/api/v1/chat/interactions",
        json={"user_message": "hello", "retrieval": {"enabled": False}},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert retrieval_client.calls == []
    assert cx_client.calls[0]["payload"]["messages"][0]["content"] == "hello"
    assert response.json()["retrieval"] is None


def test_chat_interaction_with_no_answer_skips_generation() -> None:
    client, cx_client, _, store = build_grounded_test_client(
        FakeRetrievalClient(status="NO_ANSWER")
    )

    response = client.post(
        "/api/v1/chat/interactions",
        json={"user_message": "Find missing evidence.", "retrieval": {"purpose": "search"}},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "NO_ANSWER"
    assert payload["generation"] is None
    assert cx_client.calls == []
    assert store.get(payload["interaction_id"]) == payload


def test_chat_interaction_maps_retrieval_failure_to_problem() -> None:
    client, _, _, _ = build_grounded_test_client(FailingRetrievalClient())

    response = client.post(
        "/api/v1/chat/interactions",
        json={"user_message": "hello", "retrieval": {"purpose": "search"}},
        headers=auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "cx.retrieval_unavailable"


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


def test_http_cx_generation_client_handles_non_json_error(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(503, content=b"not-json")

    monkeypatch.setattr(ae_chat.httpx, "post", fake_post)

    try:
        HttpCxGenerationClient(base_url="http://cx.test").create_generation(
            {"prompt": "hello"},
            request_id="req-1",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        )
    except ChatInteractionError as exc:
        assert exc.status_code == 503
        assert exc.error_code == "cx.request_failed"
        assert exc.detail == "CX generation request failed."
    else:
        raise AssertionError("expected ChatInteractionError")
