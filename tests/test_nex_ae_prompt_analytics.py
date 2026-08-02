from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_ae_api.analytics import (
    DEFAULT_TENANT_ID,
    DEFAULT_USER_ID,
    PromptAnalyticsError,
    PromptAnalyticsStore,
    build_prompt_event,
    classify_prompt_intent,
    estimate_prompt_tokens,
    owner_scope_from_payload,
    record_chat_prompt_analytics,
    register_prompt_analytics_routes,
    sha256_text,
)
from nex_ae_api.chat import ChatInteractionStore, register_chat_routes
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


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
        self.calls.append({"payload": payload, "request_id": request_id, "trace_id": trace_id})
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
        self.status = status

    def create_retrieval_context(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
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


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def test_classify_prompt_intent_uses_deterministic_rules() -> None:
    assert classify_prompt_intent("Summarize this document")["task_category"] == (
        "document_summary"
    )
    assert classify_prompt_intent("Upload this file")["task_category"] == (
        "content_management"
    )
    assert classify_prompt_intent("Automate this repeated workflow")["task_category"] == (
        "workflow_automation"
    )
    assert classify_prompt_intent("What is the status?") == {
        "intent_label": "general_question",
        "task_category": "knowledge_work",
        "confidence": 0.55,
        "matched_terms": [],
    }


def test_build_prompt_event_hashes_prompt_and_estimates_tokens() -> None:
    event = build_prompt_event(
        user_message="  Summarize this document  ",
        tenant_id="tenant-a",
        user_id="user-a",
        chat_interaction_id="chat-001",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        retrieval_used=True,
        retrieval_outcome="READY",
        generation_outcome="STOP",
    )

    assert event["prompt_hash"] == sha256_text("Summarize this document")
    assert event["prompt_preview"] == "Summarize this document"
    assert event["prompt_token_estimate"] == estimate_prompt_tokens(
        "Summarize this document"
    )
    assert event["metadata"]["raw_prompt_stored"] is False


def test_owner_scope_from_payload_defaults_and_rejects_invalid_values() -> None:
    assert owner_scope_from_payload({}) == (DEFAULT_TENANT_ID, DEFAULT_USER_ID)
    assert owner_scope_from_payload({"tenant_id": " tenant ", "user_id": " user "}) == (
        "tenant",
        "user",
    )

    with pytest.raises(PromptAnalyticsError):
        owner_scope_from_payload({"tenant_id": "", "user_id": "user"})
    with pytest.raises(PromptAnalyticsError):
        owner_scope_from_payload({"tenant_id": "tenant", "user_id": ""})


def test_prompt_analytics_store_updates_profile_and_recommendation() -> None:
    store = PromptAnalyticsStore()

    first = store.record_prompt_analytics(
        user_message="Summarize the quarterly document.",
        tenant_id="tenant-a",
        user_id="user-a",
        chat_interaction_id="chat-001",
        trace_id=TRACE_ID,
        request_id="request-001",
        retrieval_used=True,
        retrieval_outcome="READY",
        generation_outcome="STOP",
    )
    second = store.record_prompt_analytics(
        user_message="Summarize the policy document.",
        tenant_id="tenant-a",
        user_id="user-a",
        chat_interaction_id="chat-002",
        trace_id=TRACE_ID,
        request_id="request-002",
        retrieval_used=True,
        retrieval_outcome="READY",
        generation_outcome="STOP",
    )

    assert first["automation_recommendation"] is None
    assert second["intent_classification"]["task_category"] == "document_summary"
    assert second["user_task_profile"]["prompt_frequency"]["total"] == 2
    assert second["automation_recommendation"]["recommendation_type"] == "workflow"
    assert "Summarize the policy document." not in str(second["prompt_event"]["metadata"])


def test_workflow_prompt_creates_immediate_recommendation() -> None:
    store = PromptAnalyticsStore()

    snapshot = store.record_prompt_analytics(
        user_message="Automate this monthly workflow.",
        tenant_id="tenant-a",
        user_id="user-a",
        chat_interaction_id="chat-001",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        retrieval_used=False,
        retrieval_outcome=None,
        generation_outcome="STOP",
    )

    assert snapshot["automation_recommendation"]["task_category"] == "workflow_automation"
    assert store.list_user_recommendations(tenant_id="tenant-a", user_id="user-a")


def test_record_chat_prompt_analytics_uses_chat_record_outcomes() -> None:
    store = PromptAnalyticsStore()

    snapshot = record_chat_prompt_analytics(
        store,
        source_payload={
            "user_message": "Summarize the selected evidence.",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "locale": "en-US",
        },
        chat_record={
            "interaction_id": "chat-001",
            "trace_id": TRACE_ID,
            "request_id": REQUEST_ID,
            "retrieval": {"cx_status": "READY"},
            "generation": {"finish_reason": "STOP"},
            "status": "COMPLETED",
        },
        retrieval_used=True,
    )

    assert snapshot["prompt_event"]["locale"] == "en-US"
    assert snapshot["prompt_event"]["retrieval_outcome"] == "READY"
    assert snapshot["prompt_event"]["generation_outcome"] == "STOP"


def test_record_chat_prompt_analytics_noops_without_store() -> None:
    assert (
        record_chat_prompt_analytics(
            None,
            source_payload={"user_message": "hello"},
            chat_record={
                "interaction_id": "chat-001",
                "trace_id": TRACE_ID,
                "request_id": REQUEST_ID,
                "status": "COMPLETED",
            },
            retrieval_used=False,
        )
        is None
    )


def test_chat_route_records_prompt_analytics_for_completed_interaction() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    analytics_store = PromptAnalyticsStore()
    register_chat_routes(
        app,
        store=ChatInteractionStore(),
        cx_client=FakeCxClient(),
        analytics_store=analytics_store,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "user_message": "Summarize the selected evidence.",
            "tenant_id": "tenant-a",
            "user_id": "user-a",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    snapshot = next(iter(analytics_store.snapshots.values()))
    assert snapshot["prompt_event"]["chat_interaction_id"] == response.json()["interaction_id"]
    assert snapshot["intent_classification"]["intent_label"] == "summarize_document"


def test_chat_route_records_prompt_analytics_for_no_answer() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    analytics_store = PromptAnalyticsStore()
    register_chat_routes(
        app,
        store=ChatInteractionStore(),
        cx_client=FakeCxClient(),
        retrieval_client=FakeRetrievalClient(status="NO_ANSWER"),
        analytics_store=analytics_store,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "user_message": "Summarize missing evidence.",
            "retrieval": {"enabled": True, "query_text": "missing"},
            "tenant_id": "tenant-a",
            "user_id": "user-a",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    snapshot = next(iter(analytics_store.snapshots.values()))
    assert response.json()["status"] == "NO_ANSWER"
    assert snapshot["prompt_event"]["retrieval_used"] is True
    assert snapshot["prompt_event"]["generation_outcome"] == "NO_ANSWER"


def test_chat_route_reports_invalid_analytics_owner() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_chat_routes(
        app,
        store=ChatInteractionStore(),
        cx_client=FakeCxClient(),
        analytics_store=PromptAnalyticsStore(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat/interactions",
        json={"user_message": "hello", "tenant_id": ""},
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "ae.analytics_owner_invalid"


def test_prompt_analytics_routes_read_snapshot_profile_and_recommendations() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = PromptAnalyticsStore()
    first = store.record_prompt_analytics(
        user_message="Summarize the quarterly document.",
        tenant_id="tenant-a",
        user_id="user-a",
        chat_interaction_id="chat-001",
        trace_id=TRACE_ID,
        request_id="request-001",
        retrieval_used=True,
        retrieval_outcome="READY",
        generation_outcome="STOP",
    )
    store.record_prompt_analytics(
        user_message="Summarize the policy document.",
        tenant_id="tenant-a",
        user_id="user-a",
        chat_interaction_id="chat-002",
        trace_id=TRACE_ID,
        request_id="request-002",
        retrieval_used=True,
        retrieval_outcome="READY",
        generation_outcome="STOP",
    )
    register_prompt_analytics_routes(app, store=store)
    client = TestClient(app)

    snapshot_response = client.get(
        f"/api/v1/analytics/prompt-events/{first['prompt_event']['prompt_event_id']}",
        headers=auth_headers(),
    )
    profile_response = client.get(
        "/api/v1/analytics/users/user-a/task-profile?tenant_id=tenant-a",
        headers=auth_headers(),
    )
    recommendations_response = client.get(
        "/api/v1/analytics/users/user-a/recommendations?tenant_id=tenant-a",
        headers=auth_headers(),
    )

    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["prompt_event"]["prompt_hash"]
    assert profile_response.status_code == 200
    assert profile_response.json()["prompt_frequency"]["total"] == 2
    assert recommendations_response.status_code == 200
    assert len(recommendations_response.json()["recommendations"]) == 1


def test_prompt_analytics_routes_require_auth_and_report_not_found() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = PromptAnalyticsStore()
    register_prompt_analytics_routes(app, store=store)
    client = TestClient(app)

    auth_response = client.get("/api/v1/analytics/prompt-events/missing")
    missing_event = client.get(
        "/api/v1/analytics/prompt-events/missing",
        headers=auth_headers(),
    )
    missing_profile = client.get(
        "/api/v1/analytics/users/user-a/task-profile?tenant_id=tenant-a",
        headers=auth_headers(),
    )
    empty_recommendations = client.get(
        "/api/v1/analytics/users/user-a/recommendations?tenant_id=tenant-a",
        headers=auth_headers(),
    )

    assert auth_response.status_code == 401
    assert missing_event.status_code == 404
    assert missing_event.json()["error_code"] == "ae.prompt_event_not_found"
    assert missing_profile.status_code == 404
    assert missing_profile.json()["error_code"] == "ae.user_task_profile_not_found"
    assert empty_recommendations.status_code == 200
    assert empty_recommendations.json() == {"recommendations": []}
