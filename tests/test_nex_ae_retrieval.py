from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import nex_ae_api.retrieval as ae_retrieval
from nex_ae_api.retrieval import (
    HttpCxRetrievalClient,
    RetrievalInteractionError,
    RetrievalInteractionStore,
    browser_actor_scoped_retrieval_payload,
    build_cx_retrieval_payload,
    build_retrieval_interaction_record,
    ensure_retrieval_record_visible_to_browser,
    register_retrieval_routes,
    user_message_from_payload,
)
from nex_runtime import (
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


class FakeCxRetrievalClient:
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
            "package_hash": "a" * 64,
            "status": self.status,
            "purpose": payload["purpose"],
            "evidence_items": [{"evidence_id": "ev-001"}] if self.status == "READY" else [],
            "score_summary": {
                "best_score": 0.9 if self.status == "READY" else 0.0,
                "confidence_bucket": self.status,
            },
            "no_answer_reason": None if self.status == "READY" else "no_terms_matched",
            "warnings": ["tokenizer_fallback_used:doc-1"],
        }


class FailingCxRetrievalClient:
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
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def user_headers(
    *,
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
) -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id=tenant_id,
        user_id=user_id,
        scopes=[DEFAULT_USER_SCOPE],
        roles=["employee"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_test_client(
    cx_client: FakeCxRetrievalClient | FailingCxRetrievalClient | None = None,
) -> tuple[TestClient, FakeCxRetrievalClient | FailingCxRetrievalClient, RetrievalInteractionStore]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = RetrievalInteractionStore()
    client = cx_client or FakeCxRetrievalClient()
    register_retrieval_routes(app, store=store, cx_client=client)
    return TestClient(app), client, store


def test_user_message_from_payload_rejects_empty_message() -> None:
    try:
        user_message_from_payload({"user_message": " "})
    except RetrievalInteractionError as exc:
        assert exc.status_code == 400
        assert exc.error_code == "ae.retrieval_request_invalid"
    else:
        raise AssertionError("expected RetrievalInteractionError")


def test_build_cx_retrieval_payload_maps_ae_fields() -> None:
    payload = build_cx_retrieval_payload(
        {
            "user_message": "  Find trace evidence  ",
            "chat_document_id": "chat-001",
            "actor_claims_ref": {"actor_type": "user", "actor_id": "user-1"},
            "retrieval": {
                "query_text": "trace evidence",
                "document_scope": {"document_ids": ["doc-1"]},
                "top_k": 3,
                "include_neighbors": True,
                "purpose": "grounded_answer",
            },
        },
        trace_id=TRACE_ID,
    )

    assert payload["query_text"] == "trace evidence"
    assert payload["user_prompt"] == "Find trace evidence"
    assert payload["chat_document_id"] == "chat-001"
    assert payload["actor_claims_ref"]["actor_id"] == "user-1"
    assert payload["top_k"] == 3
    assert payload["include_neighbors"] is True
    assert payload["purpose"] == "grounded_answer"
    assert "Find trace evidence" not in payload["metadata"]["user_message_hash"]


def test_build_cx_retrieval_payload_defaults_optional_fields() -> None:
    payload = build_cx_retrieval_payload({"user_message": "hello"}, trace_id=TRACE_ID)

    assert payload["execution_mode"] == "DOCUMENT_SEARCH"
    assert payload["query_text"] == "hello"
    assert payload["actor_claims_ref"] == {"actor_type": "service", "actor_id": "nex-ae-api"}
    assert payload["retrieval_profile"] == {"search_strategy": "hybrid"}
    assert payload["top_k"] == 5
    assert payload["include_source_preview"] is True


def test_build_cx_retrieval_payload_rejects_bad_retrieval_object() -> None:
    try:
        build_cx_retrieval_payload(
            {"user_message": "hello", "retrieval": "bad"},
            trace_id=TRACE_ID,
        )
    except RetrievalInteractionError as exc:
        assert exc.status_code == 400
        assert exc.error_code == "ae.retrieval_request_invalid"
    else:
        raise AssertionError("expected RetrievalInteractionError")


def test_build_retrieval_interaction_record_maps_cx_summary() -> None:
    record = build_retrieval_interaction_record(
        source_payload={"user_message": "hello"},
        cx_payload={
            "metadata": {
                "ae_retrieval_interaction_id": "ret-001",
                "chat_document_id": "chat-001",
                "user_message_hash": "a" * 64,
            }
        },
        cx_package={
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "b" * 64,
            "status": "READY",
            "purpose": "search",
            "evidence_items": [{"evidence_id": "ev-1"}],
            "score_summary": {"best_score": 0.9, "confidence_bucket": "READY"},
            "warnings": [],
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["retrieval_interaction_id"] == "ret-001"
    assert record["cx_retrieval_package_id"] == "cx-ret-001"
    assert record["retrieval"]["evidence_count"] == 1


def test_retrieval_interaction_endpoint_requires_service_claim() -> None:
    client, _, _ = build_test_client()

    response = client.post("/api/v1/retrieval/contexts", json={"user_message": "hello"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_retrieval_interaction_endpoint_calls_cx_and_stores_record() -> None:
    client, cx_client, store = build_test_client()

    response = client.post(
        "/api/v1/retrieval/contexts",
        json={
            "user_message": "Find trace evidence",
            "retrieval": {"purpose": "grounded_answer"},
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["cx_status"] == "READY"
    assert payload["retrieval"]["evidence_count"] == 1
    assert store.get(payload["retrieval_interaction_id"]) == payload
    assert cx_client.calls[0]["payload"]["purpose"] == "grounded_answer"
    assert cx_client.calls[0]["trace_id"] == TRACE_ID


def test_retrieval_interaction_endpoint_accepts_browser_user_scope() -> None:
    client, cx_client, store = build_test_client()

    created = client.post(
        "/api/v1/retrieval/contexts",
        json={
            "user_message": "Find trace evidence",
            "actor_claims_ref": {
                "actor_type": "user",
                "actor_id": "user-a",
                "tenant_id": "tenant-a",
            },
        },
        headers=user_headers(),
    )

    payload = created.json()
    same_user_read = client.get(
        f"/api/v1/retrieval/contexts/{payload['retrieval_interaction_id']}",
        headers=user_headers(),
    )
    other_user_read = client.get(
        f"/api/v1/retrieval/contexts/{payload['retrieval_interaction_id']}",
        headers=user_headers(user_id="user-b"),
    )

    assert created.status_code == 200
    assert payload["actor_claims_ref"] == {
        "actor_type": "user",
        "actor_id": "user-a",
        "tenant_id": "tenant-a",
    }
    assert store.get(payload["retrieval_interaction_id"]) == payload
    assert same_user_read.status_code == 200
    assert other_user_read.status_code == 403
    assert other_user_read.json()["error_code"] == "ae.browser_owner_scope_mismatch"
    assert cx_client.calls[0]["payload"]["actor_claims_ref"] == payload["actor_claims_ref"]


def test_retrieval_interaction_rejects_browser_actor_scope_mismatch() -> None:
    client, cx_client, _ = build_test_client()

    response = client.post(
        "/api/v1/retrieval/contexts",
        json={
            "user_message": "Find trace evidence",
            "actor_claims_ref": {
                "actor_type": "user",
                "actor_id": "user-b",
                "tenant_id": "tenant-a",
            },
        },
        headers=user_headers(),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ae.browser_owner_scope_mismatch"
    assert cx_client.calls == []


def test_browser_actor_scope_helpers_cover_defaults_and_visibility_errors() -> None:
    class Context:
        tenant_id = "tenant-a"
        user_id = "user-a"

    context = Context()

    scoped = browser_actor_scoped_retrieval_payload(
        {"user_message": "Find trace evidence"},
        context,  # type: ignore[arg-type]
    )
    scoped_from_blank_actor = browser_actor_scoped_retrieval_payload(
        {
            "user_message": "Find trace evidence",
            "actor_claims_ref": {"tenant_id": "", "actor_id": " "},
        },
        context,  # type: ignore[arg-type]
    )

    assert browser_actor_scoped_retrieval_payload(scoped, None) == scoped
    assert scoped["actor_claims_ref"] == {
        "actor_type": "user",
        "actor_id": "user-a",
        "tenant_id": "tenant-a",
    }
    assert scoped_from_blank_actor["actor_claims_ref"] == scoped["actor_claims_ref"]

    with pytest.raises(RetrievalInteractionError) as tenant_mismatch:
        browser_actor_scoped_retrieval_payload(
            {
                "user_message": "Find trace evidence",
                "actor_claims_ref": {"tenant_id": "tenant-b", "actor_id": "user-a"},
            },
            context,  # type: ignore[arg-type]
        )
    with pytest.raises(RetrievalInteractionError) as missing_actor:
        ensure_retrieval_record_visible_to_browser(
            {"retrieval_interaction_id": "ret-001"},
            context,  # type: ignore[arg-type]
        )
    with pytest.raises(RetrievalInteractionError) as actor_mismatch:
        ensure_retrieval_record_visible_to_browser(
            {
                "actor_claims_ref": {
                    "actor_type": "user",
                    "actor_id": "user-b",
                    "tenant_id": "tenant-a",
                }
            },
            context,  # type: ignore[arg-type]
        )

    assert tenant_mismatch.value.error_code == "ae.browser_owner_scope_mismatch"
    assert missing_actor.value.error_code == "ae.browser_owner_scope_mismatch"
    assert actor_mismatch.value.error_code == "ae.browser_owner_scope_mismatch"


def test_retrieval_interaction_endpoint_maps_no_answer() -> None:
    client, _, _ = build_test_client(FakeCxRetrievalClient(status="NO_ANSWER"))

    response = client.post(
        "/api/v1/retrieval/contexts",
        json={"user_message": "Find missing evidence"},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["cx_status"] == "NO_ANSWER"
    assert payload["retrieval"]["no_answer_reason"] == "no_terms_matched"


def test_retrieval_interaction_endpoint_returns_problem_for_cx_failure() -> None:
    client, _, _ = build_test_client(FailingCxRetrievalClient())

    response = client.post(
        "/api/v1/retrieval/contexts",
        json={"user_message": "Find trace evidence"},
        headers=auth_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "cx.retrieval_unavailable"
    assert response.json()["retryable"] is True


def test_retrieval_interaction_can_be_read_back() -> None:
    client, _, _ = build_test_client()
    created = client.post(
        "/api/v1/retrieval/contexts",
        json={"user_message": "hello"},
        headers=auth_headers(),
    ).json()

    response = client.get(
        f"/api/v1/retrieval/contexts/{created['retrieval_interaction_id']}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["cx_package_hash"] == created["cx_package_hash"]


def test_retrieval_interaction_read_requires_auth() -> None:
    client, _, _ = build_test_client()

    response = client.get("/api/v1/retrieval/contexts/missing")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_retrieval_interaction_read_returns_not_found() -> None:
    client, _, _ = build_test_client()

    response = client.get(
        "/api/v1/retrieval/contexts/missing",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "ae.retrieval_interaction_not_found"


def test_http_cx_retrieval_client_posts_with_mock_token(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return httpx.Response(200, json={"retrieval_package_id": "cx-ret-001"})

    monkeypatch.setattr(ae_retrieval.httpx, "post", fake_post)

    response = HttpCxRetrievalClient(base_url="http://cx.test").create_retrieval_context(
        {"query_text": "trace"},
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["retrieval_package_id"] == "cx-ret-001"
    assert calls[0]["args"] == ("http://cx.test/api/v1/retrieval/context",)
    assert calls[0]["kwargs"]["headers"]["X-Service-ID"] == "nex-ae-api"
    assert calls[0]["kwargs"]["headers"]["Authorization"].startswith(
        "Bearer nex-mock-service."
    )


def test_http_cx_retrieval_client_maps_problem_response(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(
            422,
            json={
                "error_code": "cx.top_k_invalid",
                "detail": "Bad top_k",
                "retryable": False,
            },
        )

    monkeypatch.setattr(ae_retrieval.httpx, "post", fake_post)

    try:
        HttpCxRetrievalClient(base_url="http://cx.test").create_retrieval_context(
            {"query_text": "trace"},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    except RetrievalInteractionError as exc:
        assert exc.status_code == 422
        assert exc.error_code == "cx.top_k_invalid"
    else:
        raise AssertionError("expected RetrievalInteractionError")


def test_http_cx_retrieval_client_handles_non_object_error(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return httpx.Response(503, json=["bad"])

    monkeypatch.setattr(ae_retrieval.httpx, "post", fake_post)

    try:
        HttpCxRetrievalClient(base_url="http://cx.test").create_retrieval_context(
            {"query_text": "trace"},
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    except RetrievalInteractionError as exc:
        assert exc.error_code == "cx.retrieval_request_failed"
    else:
        raise AssertionError("expected RetrievalInteractionError")
