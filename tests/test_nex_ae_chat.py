from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import nex_ae_api.chat as ae_chat
from nex_ae_api.chat import (
    ChatInteractionError,
    ChatInteractionStore,
    HttpCxGenerationClient,
    SqlAlchemyChatInteractionStore,
    attach_retrieval_package_to_generation_payload,
    artifact_actions_for_record,
    artifact_record_from_payload,
    build_default_chat_store,
    build_chat_artifact_ref,
    build_chat_interaction_record,
    build_cx_generation_payload,
    build_generation_quality_rejected_chat_interaction_record,
    build_grounded_user_message,
    build_no_answer_chat_interaction_record,
    generation_quality_rejection_failure_summary,
    generation_quality_rejection_stage,
    grounded_response_quality_contract,
    register_chat_routes,
    retrieval_quality_warning_contract,
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
        retrieval_ref = payload.get("retrieval_package_ref")
        grounded = isinstance(retrieval_ref, dict)
        return {
            "cx_generation_id": "cx-gen-001",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": payload["provider_capability"],
            "mo_generation_id": "mo-gen-001",
            "request_metadata": {
                "grounding_required": grounded,
                "retrieval_package_id": retrieval_ref.get("retrieval_package_id")
                if grounded
                else None,
                "retrieval_package_hash": retrieval_ref.get("package_hash")
                if grounded
                else None,
                "selected_evidence_count": len(payload.get("selected_evidence_ids", [])),
                "structured_draft_id": "draft-001" if grounded else None,
                "draft_validation_status": "VALIDATED" if grounded else None,
                "grounded_response_quality_audit_schema_version": (
                    "cx_grounded_response_citation_quality_audit.v1"
                    if grounded
                    else None
                ),
                "grounded_response_quality_status": "PASS" if grounded else None,
                "grounded_response_quality_issue_count": 0 if grounded else None,
            },
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "Mock answer.",
            },
            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        }


class RejectingCxClient:
    def __init__(
        self,
        *,
        error_code: str = "cx.retrieval_package_quality_blocked",
        detail: str = "Retrieval package quality guard blocked private-doc-id.",
        retryable: bool = False,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable

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
        raise ChatInteractionError(
            status_code=409,
            error_code=self.error_code,
            detail=self.detail,
            retryable=self.retryable,
        )


class FakeRetrievalClient:
    def __init__(
        self,
        *,
        status: str = "READY",
        warnings: list[str] | None = None,
        quality_flags: list[str] | None = None,
        best_score: float | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status
        self.warnings = warnings or []
        self.quality_flags = quality_flags or []
        self.best_score = best_score

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
        best_score = self.best_score
        if best_score is None:
            best_score = 0.9 if self.status == "READY" else 0.0
        return {
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "b" * 64,
            "status": self.status,
            "purpose": payload["purpose"],
            "evidence_items": [
                {
                    "evidence_id": "evidence-001",
                    "citation_label": "[1]",
                    "text": "Trace evidence from CX.",
                    "quality_flags": self.quality_flags,
                }
            ]
            if self.status == "READY"
            else [],
            "score_summary": {
                "best_score": best_score,
                "confidence_bucket": self.status,
                "low_confidence_threshold": 0.2,
            },
            "retrieval_profile": {
                "confidence_policy": {"low_confidence_threshold": 0.2},
            },
            "no_answer_reason": None if self.status == "READY" else "no_terms_matched",
            "warnings": self.warnings,
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


def sqlite_chat_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_chat_interactions (
                    chat_interaction_id TEXT PRIMARY KEY,
                    interaction_schema_version TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    user_message_hash TEXT NOT NULL,
                    user_message_preview TEXT NOT NULL,
                    cx_retrieval_package_id TEXT,
                    cx_retrieval_package_hash TEXT,
                    cx_generation_id TEXT,
                    cx_generation_status TEXT,
                    retrieval_summary TEXT NOT NULL,
                    generation_summary TEXT NOT NULL,
                    failure_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_chat_artifact_refs (
                    chat_artifact_ref_id TEXT PRIMARY KEY,
                    chat_interaction_id TEXT NOT NULL,
                    chat_document_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    artifact_version_id TEXT NOT NULL,
                    display_title TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    artifact_status TEXT NOT NULL,
                    primary_format TEXT NOT NULL,
                    available_formats TEXT NOT NULL,
                    preview_route TEXT,
                    download_routes TEXT NOT NULL,
                    source_generation_id TEXT NOT NULL,
                    source_content_hash TEXT NOT NULL,
                    quality_summary TEXT NOT NULL,
                    actions TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (chat_interaction_id, artifact_id, artifact_version_id)
                )
                """
            )
        )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


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


def test_chat_store_attach_handles_missing_and_same_artifact_new_version() -> None:
    store = ChatInteractionStore()
    record = {
        "interaction_id": "interaction-001",
        "chat_document_id": "chat-001",
        "artifact_refs": [
            {
                "artifact_id": "artifact-001",
                "artifact_version_id": "artifact-version-old",
            }
        ],
        "updated_at": "2026-08-29T00:00:00Z",
    }
    artifact_ref = {
        "artifact_id": "artifact-001",
        "artifact_version_id": "artifact-version-new",
    }

    assert store.attach_artifact_ref(
        interaction_id="missing",
        artifact_ref=artifact_ref,
        updated_at="2026-08-29T00:00:01Z",
    ) is None
    store.save(record)
    updated = store.attach_artifact_ref(
        interaction_id="interaction-001",
        artifact_ref=artifact_ref,
        updated_at="2026-08-29T00:00:01Z",
    )

    assert updated["artifact_refs"][-1] == artifact_ref
    assert updated["updated_at"] == "2026-08-29T00:00:01Z"


def test_sqlalchemy_chat_store_persists_interaction_and_artifact_refs() -> None:
    session_factory = sqlite_chat_session_factory()
    store = SqlAlchemyChatInteractionStore(session_factory)
    interaction_id = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
    chat_document_id = "62cbb468-147e-5e66-9bd8-4551a5807cf6"
    record = build_chat_interaction_record(
        source_payload={
            "interaction_id": interaction_id,
            "chat_document_id": chat_document_id,
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": "Summarize the rendered artifact.",
        },
        cx_payload={
            "client_request_id": interaction_id,
            "metadata": {
                "chat_document_id": chat_document_id,
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
            "usage": {"total_tokens": 5},
        },
        request_id="request-001",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    artifact_record = sample_artifact_record(
        chat_document_id=chat_document_id,
        interaction_id=interaction_id,
    )
    artifact_ref = build_chat_artifact_ref(artifact_record)

    assert store.save(record) == record
    assert store.get(interaction_id)["artifact_refs"] == []

    attached = store.attach_artifact_ref(
        interaction_id=interaction_id,
        artifact_ref=artifact_ref,
        updated_at="2026-08-29T00:00:00Z",
    )
    repeated = store.attach_artifact_ref(
        interaction_id=interaction_id,
        artifact_ref=artifact_ref,
        updated_at="2026-08-29T00:00:01Z",
    )
    artifact_ref_new_version = {
        **artifact_ref,
        "artifact_version_id": "artifact-version-002",
    }
    expanded = store.attach_artifact_ref(
        interaction_id=interaction_id,
        artifact_ref=artifact_ref_new_version,
        updated_at="2026-08-29T00:00:02Z",
    )

    assert attached is not None
    assert attached["tenant_id"] == "tenant-a"
    assert attached["user_id"] == "user-a"
    assert attached["generation"]["usage"] == {"total_tokens": 5}
    assert attached["artifact_refs"] == [artifact_ref]
    assert repeated == attached
    assert expanded["artifact_refs"] == [artifact_ref, artifact_ref_new_version]
    assert store.get(interaction_id)["artifact_refs"] == [
        artifact_ref,
        artifact_ref_new_version,
    ]


def test_sqlalchemy_chat_store_persists_failed_record_and_missing_attach() -> None:
    session_factory = sqlite_chat_session_factory()
    store = SqlAlchemyChatInteractionStore(session_factory)
    interaction_id = "aaaaaaaa-8f22-4f72-9b47-b481dc21bb21"
    chat_document_id = "bbbbbbbb-147e-5e66-9bd8-4551a5807cf6"
    record = build_generation_quality_rejected_chat_interaction_record(
        source_payload={
            "interaction_id": interaction_id,
            "chat_document_id": chat_document_id,
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": "Summarize trace evidence.",
        },
        cx_payload={
            "client_request_id": interaction_id,
            "metadata": {
                "chat_document_id": chat_document_id,
                "user_message_hash": "b" * 64,
            },
        },
        retrieval_package={
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "c" * 64,
            "status": "READY",
            "evidence_items": [],
            "score_summary": {"best_score": 0.1, "confidence_bucket": "READY"},
            "warnings": [],
        },
        failure=ChatInteractionError(
            status_code=409,
            error_code="cx.retrieval_package_quality_blocked",
            detail="blocked private details",
        ),
        request_id="request-002",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    store.save(record)
    loaded = store.get(interaction_id)

    assert loaded["generation"] is None
    assert loaded["failure"]["error_code"] == "cx.retrieval_package_quality_blocked"
    assert loaded["retrieval"]["cx_retrieval_package_id"] == "cx-ret-001"
    assert store.attach_artifact_ref(
        interaction_id="missing",
        artifact_ref=build_chat_artifact_ref(
            sample_artifact_record(
                chat_document_id=chat_document_id,
                interaction_id=interaction_id,
            )
        ),
        updated_at="2026-08-29T00:00:02Z",
    ) is None
    assert store.delete(interaction_id) == 1
    assert store.get(interaction_id) is None


def test_chat_routes_use_sqlalchemy_default_store_when_persistence_attached() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    session_factory = sqlite_chat_session_factory()
    app.state.nex_persistence = SimpleNamespace(api_session_factory=session_factory)
    cx_client = FakeCxClient()
    register_chat_routes(app, cx_client=cx_client)
    client = TestClient(app)
    interaction_id = "cccccccc-8f22-4f72-9b47-b481dc21bb21"
    chat_document_id = "dddddddd-147e-5e66-9bd8-4551a5807cf6"

    created = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": interaction_id,
            "chat_document_id": chat_document_id,
            "tenant_id": "tenant-a",
            "user_id": "user-a",
            "user_message": "Create a report artifact.",
        },
        headers=auth_headers(),
    )
    attached = client.post(
        f"/api/v1/chat/interactions/{interaction_id}/artifact-links",
        json={
            "artifact": sample_artifact_record(
                chat_document_id=chat_document_id,
                interaction_id=interaction_id,
            )
        },
        headers=auth_headers(),
    )
    readback = client.get(
        f"/api/v1/chat/interactions/{interaction_id}",
        headers=auth_headers(),
    )

    assert created.status_code == 200
    assert build_default_chat_store(app).__class__ is SqlAlchemyChatInteractionStore
    assert attached.status_code == 200
    assert len(attached.json()["artifact_refs"]) == 1
    assert readback.json()["artifact_refs"] == attached.json()["artifact_refs"]


def test_default_chat_store_falls_back_to_in_memory_without_persistence() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])

    assert build_default_chat_store(app) is ae_chat.DEFAULT_CHAT_STORE


def test_chat_artifact_link_list_requires_auth() -> None:
    client, _, _ = build_test_client()

    response = client.get("/api/v1/chat/interactions/interaction-001/artifact-links")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_chat_artifact_ref_rejects_missing_required_text_fields() -> None:
    missing_title = sample_artifact_record()
    missing_title["display_title"] = " "

    try:
        build_chat_artifact_ref(missing_title)
    except ChatInteractionError as exc:
        assert exc.error_code == "ae.artifact_record_invalid"
        assert "display_title" in exc.detail
    else:
        raise AssertionError("expected ChatInteractionError")


def test_chat_sql_helpers_cover_postgresql_json_and_datetime_branches() -> None:
    assert ae_chat._json_param_expr("payload", "postgresql") == "CAST(:payload AS jsonb)"
    assert ae_chat._json_param_expr("payload", "sqlite") == ":payload"
    assert ae_chat._json_value(None, {"fallback": True}) == {"fallback": True}
    assert ae_chat._json_value({"already": "decoded"}, {}) == {"already": "decoded"}
    assert ae_chat._datetime_value(ae_chat.datetime(2026, 8, 29, tzinfo=ae_chat.UTC)) == (
        "2026-08-29T00:00:00Z"
    )


def test_sqlalchemy_chat_store_wraps_database_errors() -> None:
    engine = create_engine("sqlite+pysqlite://", future=True)
    store = SqlAlchemyChatInteractionStore(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    record = build_chat_interaction_record(
        source_payload={"user_message": "hello"},
        cx_payload={
            "client_request_id": "eeeeeeee-8f22-4f72-9b47-b481dc21bb21",
            "metadata": {
                "chat_document_id": "ffffffff-147e-5e66-9bd8-4551a5807cf6",
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
        request_id="request-003",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    for action in (
        lambda: store.save(record),
        lambda: store.get(record["interaction_id"]),
        lambda: store.attach_artifact_ref(
            interaction_id=record["interaction_id"],
            artifact_ref=build_chat_artifact_ref(
                sample_artifact_record(
                    chat_document_id=record["chat_document_id"],
                    interaction_id=record["interaction_id"],
                )
            ),
            updated_at="2026-08-29T00:00:03Z",
        ),
        lambda: store.delete(record["interaction_id"]),
    ):
        try:
            action()
        except ChatInteractionError as exc:
            assert exc.status_code == 503
            assert exc.error_code == "ae.chat_store_unavailable"
            assert exc.retryable is True
        else:
            raise AssertionError("expected ChatInteractionError")


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
    assert record["generation"]["grounded_response_quality"] == {
        "contract_schema_version": "ae_chat_grounded_response_quality.v1",
        "source_audit_schema_version": None,
        "boundary_status": "NOT_REQUIRED",
        "citation_status": "NOT_REQUIRED",
        "issue_count": 0,
        "recommended_action": "proceed",
        "grounding_required": False,
        "retrieval_package_id": None,
        "retrieval_package_hash": None,
        "structured_draft_id": None,
        "raw_output_included": False,
        "evidence_text_included": False,
        "prompt_text_included": False,
        "provider_detail_included": False,
    }
    assert record["retrieval"] is None
    assert record["artifact_refs"] == []


def test_grounded_response_quality_contract_maps_cx_request_metadata() -> None:
    contract = grounded_response_quality_contract(
        {
            "request_metadata": {
                "grounding_required": True,
                "retrieval_package_id": "cx-ret-001",
                "retrieval_package_hash": "b" * 64,
                "structured_draft_id": "draft-001",
                "draft_validation_status": "VALIDATED",
                "grounded_response_quality_audit_schema_version": (
                    "cx_grounded_response_citation_quality_audit.v1"
                ),
                "grounded_response_quality_status": "PASS",
                "grounded_response_quality_issue_count": 0,
                "raw_output": "private generated output",
            }
        }
    )

    assert contract == {
        "contract_schema_version": "ae_chat_grounded_response_quality.v1",
        "source_audit_schema_version": (
            "cx_grounded_response_citation_quality_audit.v1"
        ),
        "boundary_status": "PASS",
        "citation_status": "VALIDATED",
        "issue_count": 0,
        "recommended_action": "proceed",
        "grounding_required": True,
        "retrieval_package_id": "cx-ret-001",
        "retrieval_package_hash": "b" * 64,
        "structured_draft_id": "draft-001",
        "raw_output_included": False,
        "evidence_text_included": False,
        "prompt_text_included": False,
        "provider_detail_included": False,
    }
    assert "private generated output" not in str(contract)


def test_grounded_response_quality_contract_handles_sparse_statuses() -> None:
    warn = grounded_response_quality_contract(
        {
            "request_metadata": {
                "grounding_required": True,
                "draft_validation_status": "VALIDATED",
                "grounded_response_quality_status": "WARN",
                "grounded_response_quality_issue_count": 1,
            }
        }
    )
    failed = grounded_response_quality_contract(
        {
            "request_metadata": {
                "grounding_required": True,
                "draft_validation_status": "INVALID",
                "grounded_response_quality_status": "FAIL",
                "grounded_response_quality_issue_count": -3,
            }
        }
    )
    unknown = grounded_response_quality_contract(
        {
            "request_metadata": {
                "grounding_required": True,
                "draft_validation_status": " ",
                "grounded_response_quality_status": " ",
                "grounded_response_quality_issue_count": True,
            }
        }
    )

    assert warn["recommended_action"] == "proceed_with_caveat"
    assert warn["issue_count"] == 1
    assert failed["recommended_action"] == "show_error"
    assert failed["boundary_status"] == "FAIL"
    assert failed["issue_count"] == 0
    assert unknown["boundary_status"] == "UNKNOWN"
    assert unknown["citation_status"] == "UNKNOWN"
    assert unknown["recommended_action"] == "proceed_with_caveat"


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
            "evidence_items": [
                {
                    "evidence_id": "evidence-001",
                    "citation_label": "[1]",
                    "text": "Evidence.",
                    "quality_flags": ["debug_checked:private-doc"],
                }
            ],
            "score_summary": {
                "best_score": 0.9,
                "confidence_bucket": "READY",
                "low_confidence_threshold": 0.2,
            },
            "warnings": ["tokenizer_fallback_used:private-doc"],
        },
    )

    assert updated["metadata"]["retrieval_package_id"] == "cx-ret-001"
    assert updated["metadata"]["retrieval_evidence_count"] == 1
    assert updated["metadata"]["retrieval_warning_count"] == 1
    assert updated["metadata"]["retrieval_warning_kinds"] == [
        "tokenizer_fallback_used"
    ]
    assert updated["metadata"]["retrieval_quality_flag_kinds"] == ["debug_checked"]
    assert updated["metadata"]["retrieval_quality_recommended_action"] == (
        "proceed_with_caveat"
    )
    assert "Supporting evidence" in updated["messages"][0]["content"]
    assert "private-doc" not in str(updated["metadata"])


def test_retrieval_summary_maps_package() -> None:
    summary = retrieval_summary(
        {
            "retrieval_package_id": "cx-ret-001",
            "package_hash": "b" * 64,
            "status": "READY",
            "evidence_items": [
                {
                    "evidence_id": "ev-1",
                    "quality_flags": ["debug_checked:private-doc"],
                }
            ],
            "score_summary": {
                "best_score": 0.9,
                "confidence_bucket": "READY",
                "low_confidence_threshold": 0.2,
            },
            "warnings": ["tokenizer_fallback_used:private-doc"],
        }
    )

    assert summary["cx_retrieval_package_id"] == "cx-ret-001"
    assert summary["evidence_count"] == 1
    assert summary["warnings"] == ["tokenizer_fallback_used"]
    assert summary["quality_warnings"] == {
        "contract_schema_version": "ae_chat_retrieval_quality_warning.v1",
        "warning_count": 1,
        "warning_kinds": ["tokenizer_fallback_used"],
        "quality_flag_count": 1,
        "quality_flag_kinds": ["debug_checked"],
        "low_confidence_threshold": 0.2,
        "best_score_below_threshold": False,
        "status_caveat_required": True,
        "recommended_action": "proceed_with_caveat",
        "raw_warning_details_included": False,
    }
    assert "private-doc" not in str(summary)


def test_retrieval_quality_warning_contract_maps_actions_and_thresholds() -> None:
    clear = retrieval_quality_warning_contract(
        {
            "status": "READY",
            "evidence_items": [],
            "score_summary": {"best_score": 0.9, "confidence_bucket": "READY"},
            "warnings": [],
        }
    )
    low_score = retrieval_quality_warning_contract(
        {
            "status": "READY",
            "evidence_items": [],
            "retrieval_profile": {
                "confidence_policy": {"low_confidence_threshold": 0.8}
            },
            "score_summary": {"best_score": 0.3, "confidence_bucket": "READY"},
            "warnings": [],
        }
    )
    no_answer = retrieval_quality_warning_contract(
        {
            "status": "NO_ANSWER",
            "evidence_items": [],
            "score_summary": {"best_score": 0.0, "confidence_bucket": "NO_ANSWER"},
            "warnings": [],
        }
    )
    failed = retrieval_quality_warning_contract(
        {
            "status": "FAILED",
            "evidence_items": [],
            "score_summary": {"best_score": 0.0, "confidence_bucket": "FAILED"},
            "warnings": [],
        }
    )

    assert clear["recommended_action"] == "proceed"
    assert clear["status_caveat_required"] is False
    assert clear["low_confidence_threshold"] == 0.2
    assert low_score["recommended_action"] == "ask_confirmation"
    assert low_score["best_score_below_threshold"] is True
    assert low_score["low_confidence_threshold"] == 0.8
    assert no_answer["recommended_action"] == "show_no_answer"
    assert failed["recommended_action"] == "show_error"


def test_retrieval_quality_warning_contract_handles_sparse_and_mixed_inputs() -> None:
    contract = retrieval_quality_warning_contract(
        {
            "status": " ",
            "evidence_items": [
                "not-an-evidence-object",
                {"quality_flags": ["low_source_confidence:private-doc", 42]},
            ],
            "score_summary": {
                "best_score": True,
                "confidence_bucket": " ",
                "low_confidence_threshold": True,
            },
            "warnings": ["permission_filtered:private-doc", 7],
        }
    )
    low_bucket = retrieval_quality_warning_contract(
        {
            "status": "READY",
            "evidence_items": [],
            "score_summary": {
                "best_score": 0.9,
                "confidence_bucket": "LOW_CONFIDENCE",
            },
            "warnings": [],
        }
    )
    partial = retrieval_quality_warning_contract(
        {
            "status": "PARTIAL",
            "evidence_items": [],
            "score_summary": {"best_score": 0.9, "confidence_bucket": "READY"},
            "warnings": [],
        }
    )

    assert contract["warning_count"] == 1
    assert contract["warning_kinds"] == ["permission_filtered"]
    assert contract["quality_flag_count"] == 1
    assert contract["quality_flag_kinds"] == ["low_source_confidence"]
    assert contract["low_confidence_threshold"] == 0.2
    assert contract["best_score_below_threshold"] is False
    assert contract["recommended_action"] == "proceed_with_caveat"
    assert contract["raw_warning_details_included"] is False
    assert "private-doc" not in str(contract)
    assert low_bucket["recommended_action"] == "ask_confirmation"
    assert partial["recommended_action"] == "proceed_with_caveat"


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


def test_build_generation_quality_rejected_chat_interaction_record_is_redacted() -> None:
    cx_payload = build_cx_generation_payload(
        {
            "interaction_id": "interaction-001",
            "chat_document_id": "chat-001",
            "user_message": "Summarize private evidence.",
            "retrieval": {"enabled": True},
        },
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    retrieval_package = {
        "retrieval_package_id": "cx-ret-001",
        "package_hash": "b" * 64,
        "status": "READY",
        "evidence_items": [
            {
                "evidence_id": "ev-1",
                "quality_flags": ["low_source_confidence:private-doc-id"],
            }
        ],
        "score_summary": {"best_score": 0.8, "confidence_bucket": "READY"},
        "warnings": ["source_summary_missing:private-doc-id"],
    }
    failure = ChatInteractionError(
        status_code=409,
        error_code="cx.retrieval_package_quality_blocked",
        detail="Blocked because private-doc-id had weak source metadata.",
    )

    record = build_generation_quality_rejected_chat_interaction_record(
        source_payload={"user_message": "Summarize private evidence."},
        cx_payload=cx_payload,
        retrieval_package=retrieval_package,
        failure=failure,
        request_id="req",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )

    assert record["status"] == "FAILED"
    assert record["cx_status"] == "FAILED"
    assert record["cx_generation_id"] is None
    assert record["generation"] is None
    assert record["failure"] == {
        "failure_schema_version": "ae_chat_generation_quality_rejection.v1",
        "error_code": "cx.retrieval_package_quality_blocked",
        "failed_stage": "retrieval_package_quality",
        "owner_service": "nex-cx",
        "retryable": False,
        "retrieval_quality_recommended_action": "proceed_with_caveat",
        "recommended_action": "show_error",
        "raw_error_detail_included": False,
    }
    assert record["retrieval"]["warnings"] == ["source_summary_missing"]
    assert record["retrieval"]["quality_warnings"]["quality_flag_kinds"] == [
        "low_source_confidence"
    ]
    assert "private-doc-id" not in str(record)


def test_generation_quality_rejection_failure_summary_maps_not_ready_action() -> None:
    summary = generation_quality_rejection_failure_summary(
        ChatInteractionError(
            status_code=409,
            error_code="cx.retrieval_package_not_ready",
            detail="Retrieval package status is LOW_CONFIDENCE.",
        ),
        {
            "status": "LOW_CONFIDENCE",
            "evidence_items": [],
            "score_summary": {
                "best_score": 0.1,
                "confidence_bucket": "LOW_CONFIDENCE",
            },
            "warnings": [],
        },
    )

    assert summary["failed_stage"] == "retrieval_package_status"
    assert summary["retrieval_quality_recommended_action"] == "ask_confirmation"
    assert summary["recommended_action"] == "ask_confirmation"
    assert generation_quality_rejection_stage("cx.other") == (
        "generation_quality_rejection"
    )


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
    assert payload["generation"]["grounded_response_quality"]["boundary_status"] == (
        "PASS"
    )
    assert payload["generation"]["grounded_response_quality"][
        "retrieval_package_id"
    ] == "cx-ret-001"
    assert retrieval_client.calls[0]["payload"]["purpose"] == "grounded_answer"
    assert cx_client.calls[0]["payload"]["metadata"]["retrieval_package_id"] == "cx-ret-001"
    assert "Trace evidence from CX." in cx_client.calls[0]["payload"]["messages"][0]["content"]
    assert store.get(payload["interaction_id"]) == payload


def test_chat_interaction_wires_retrieval_quality_warnings_to_record_and_generation() -> None:
    client, cx_client, _, _ = build_grounded_test_client(
        FakeRetrievalClient(
            warnings=["tokenizer_fallback_used:private-doc-id"],
            quality_flags=["debug_checked:private-doc-id"],
        )
    )

    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "user_message": "Summarize trace evidence.",
            "retrieval": {"purpose": "grounded_answer", "top_k": 1},
        },
        headers=auth_headers(),
    )

    payload = response.json()
    retrieval = payload["retrieval"]
    generation_metadata = cx_client.calls[0]["payload"]["metadata"]

    assert response.status_code == 200
    assert retrieval["warnings"] == ["tokenizer_fallback_used"]
    assert retrieval["quality_warnings"]["warning_count"] == 1
    assert retrieval["quality_warnings"]["warning_kinds"] == [
        "tokenizer_fallback_used"
    ]
    assert retrieval["quality_warnings"]["quality_flag_kinds"] == ["debug_checked"]
    assert retrieval["quality_warnings"]["recommended_action"] == (
        "proceed_with_caveat"
    )
    assert payload["generation"]["grounded_response_quality"] == {
        "contract_schema_version": "ae_chat_grounded_response_quality.v1",
        "source_audit_schema_version": (
            "cx_grounded_response_citation_quality_audit.v1"
        ),
        "boundary_status": "PASS",
        "citation_status": "VALIDATED",
        "issue_count": 0,
        "recommended_action": "proceed",
        "grounding_required": True,
        "retrieval_package_id": "cx-ret-001",
        "retrieval_package_hash": "b" * 64,
        "structured_draft_id": "draft-001",
        "raw_output_included": False,
        "evidence_text_included": False,
        "prompt_text_included": False,
        "provider_detail_included": False,
    }
    assert generation_metadata["retrieval_warning_count"] == 1
    assert generation_metadata["retrieval_warning_kinds"] == [
        "tokenizer_fallback_used"
    ]
    assert generation_metadata["retrieval_quality_flag_kinds"] == ["debug_checked"]
    assert generation_metadata["retrieval_quality_recommended_action"] == (
        "proceed_with_caveat"
    )
    assert "private-doc-id" not in str(retrieval)
    assert "private-doc-id" not in str(generation_metadata)


def test_chat_interaction_maps_quality_rejection_to_failed_record() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    cx_client = RejectingCxClient(
        error_code="cx.retrieval_package_quality_blocked",
        detail="Retrieval package quality guard blocked private-doc-id.",
    )
    retrieval_client = FakeRetrievalClient(
        warnings=["source_summary_missing:private-doc-id"],
        quality_flags=["low_source_confidence:private-doc-id"],
    )
    register_chat_routes(
        app,
        store=store,
        cx_client=cx_client,
        retrieval_client=retrieval_client,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "interaction-001",
            "chat_document_id": "chat-001",
            "user_message": "Summarize trace evidence.",
            "retrieval": {"purpose": "grounded_answer", "top_k": 1},
        },
        headers=auth_headers(),
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "FAILED"
    assert payload["cx_status"] == "FAILED"
    assert payload["generation"] is None
    assert payload["failure"]["error_code"] == "cx.retrieval_package_quality_blocked"
    assert payload["failure"]["failed_stage"] == "retrieval_package_quality"
    assert payload["failure"]["recommended_action"] == "show_error"
    assert payload["failure"]["raw_error_detail_included"] is False
    assert payload["retrieval"]["warnings"] == ["source_summary_missing"]
    assert payload["retrieval"]["quality_warnings"]["quality_flag_kinds"] == [
        "low_source_confidence"
    ]
    assert store.get("interaction-001") == payload
    assert len(cx_client.calls) == 1
    assert "private-doc-id" not in str(payload)


def test_chat_interaction_keeps_non_quality_generation_failure_as_problem() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    register_chat_routes(
        app,
        store=store,
        cx_client=RejectingCxClient(
            error_code="mo.provider_timeout",
            detail="MO provider timeout.",
            retryable=True,
        ),
        retrieval_client=FakeRetrievalClient(),
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "interaction-001",
            "user_message": "Summarize trace evidence.",
            "retrieval": {"purpose": "grounded_answer"},
        },
        headers=auth_headers(),
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "mo.provider_timeout"
    assert store.get("interaction-001") is None


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
