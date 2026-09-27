from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_ae_api.chat import (
    ChatInteractionError,
    ChatInteractionStore,
    SqlAlchemyChatInteractionStore,
    build_policy_generation_summary,
    register_chat_routes,
)
from nex_ae_api.prompt_persistence import PromptRepositoryError
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.prompts import PromptRegistryStore


class RecordingGenerationClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    def create_generation(self, payload, *, request_id, trace_id):
        self.calls.append(payload)
        if self.fail:
            raise ChatInteractionError(503, "mo.provider_unavailable", "unavailable", True)
        retrieval = payload.get("retrieval_package_ref")
        return {
            "cx_generation_id": "cx-policy-001",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": payload["provider_capability"],
            "mo_generation_id": "mo-policy-001",
            "request_metadata": {
                "grounding_required": retrieval is not None,
                "retrieval_package_id": (
                    retrieval.get("retrieval_package_id") if retrieval else None
                ),
                "retrieval_package_hash": (
                    retrieval.get("package_hash") if retrieval else None
                ),
                "selected_evidence_count": len(
                    payload.get("selected_evidence_ids", [])
                ),
            },
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "Policy answer.",
            },
            "usage": {"total_tokens": 5},
        }


class RecordingRetrievalClient:
    def __init__(self, *, status: str = "READY") -> None:
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def create_retrieval_context(self, payload, *, request_id, trace_id):
        self.calls.append(payload)
        ready = self.status == "READY"
        return {
            "retrieval_package_id": "retrieval-policy-001",
            "package_hash": "b" * 64,
            "status": self.status,
            "purpose": payload["purpose"],
            "evidence_items": [
                {
                    "evidence_id": "evidence-policy-001",
                    "citation_label": "[1]",
                    "text": "private runtime evidence",
                    "quality_flags": [],
                }
            ]
            if ready
            else [],
            "score_summary": {
                "best_score": 0.9 if ready else 0.0,
                "confidence_bucket": self.status,
            },
            "warnings": [],
            "no_answer_reason": None if ready else "no_terms_matched",
        }


def headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-runtime-policy",
        "traceparent": (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ),
    }


def client_with_policy(
    *,
    generation=None,
    retrieval=None,
    chat_store=None,
    prompt_store=None,
) -> tuple[TestClient, Any, Any, Any, Any]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    generations = generation or RecordingGenerationClient()
    retrievals = retrieval or RecordingRetrievalClient()
    chats = chat_store or ChatInteractionStore()
    prompts = prompt_store or PromptRegistryStore()
    if isinstance(prompts, PromptRegistryStore):
        seed_ae_prompt_registry(prompts)
    register_chat_routes(
        app,
        store=chats,
        cx_client=generations,
        retrieval_client=retrievals,
        prompt_store=prompts,
    )
    return TestClient(app), generations, retrievals, chats, prompts


def test_general_chat_persists_exact_policy_and_prompt_render_lineage() -> None:
    client, generation, retrieval, store, prompts = client_with_policy()

    response = client.post(
        "/api/v1/chat/interactions",
        json={"interaction_id": "general-policy-001", "user_message": "private hello"},
        headers=headers(),
    )

    assert response.status_code == 200
    body = response.json()
    policy = body["generation"]["policy"]
    package = policy["generation_policy_package"]
    assert body["status"] == "COMPLETED"
    assert policy["runtime_policy_snapshot"]["intent_decision"][
        "execution_mode"
    ] == "GENERAL_ANSWER"
    assert package["prompt_contract_ref"]["prompt_binding_key"] == (
        "ae.general_answer.default"
    )
    assert package["generation_parameters"]["max_output_tokens"] == 512
    assert generation.calls[0]["client_package_hash"] == package[
        "client_package_hash"
    ]
    assert retrieval.calls == []
    assert store.get("general-policy-001") == body
    event = prompts.get_render_event(
        policy["prompt_render_event_ref"]["prompt_render_event_id"]
    )
    assert event["user_prompt_hash"] == body["user_message_hash"]
    assert "private hello" not in str(policy)


def test_summary_chat_binds_retrieval_and_policy_package_without_evidence_text() -> None:
    client, generation, retrieval, _, _ = client_with_policy()

    response = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "summary-policy-001",
            "user_message": "이 문서를 요약해줘",
        },
        headers=headers(),
    )

    assert response.status_code == 200
    body = response.json()
    package = body["generation"]["policy"]["generation_policy_package"]
    assert package["execution_mode"] == "DOCUMENT_SUMMARY"
    assert package["retrieval_package_ref"]["retrieval_package_id"] == (
        "retrieval-policy-001"
    )
    assert package["selected_evidence_ids"] == ["evidence-policy-001"]
    assert "private runtime evidence" not in str(package)
    assert len(retrieval.calls) == 1
    assert generation.calls[0]["metadata"]["client_package_hash"] == package[
        "client_package_hash"
    ]


def test_no_answer_and_provider_failure_keep_policy_snapshot() -> None:
    no_answer, generation, _, _, _ = client_with_policy(
        retrieval=RecordingRetrievalClient(status="NO_ANSWER")
    )
    no_answer_response = no_answer.post(
        "/api/v1/chat/interactions",
        json={"user_message": "ground this", "retrieval": {"enabled": True}},
        headers=headers(),
    )
    assert no_answer_response.status_code == 200
    assert no_answer_response.json()["status"] == "NO_ANSWER"
    assert no_answer_response.json()["generation"]["policy"][
        "generation_policy_package"
    ] is None
    assert generation.calls == []

    failed, _, _, failed_store, _ = client_with_policy(
        generation=RecordingGenerationClient(fail=True)
    )
    failed_response = failed.post(
        "/api/v1/chat/interactions",
        json={"interaction_id": "failed-policy-001", "user_message": "hello"},
        headers=headers(),
    )
    assert failed_response.status_code == 503
    failed_record = failed_store.get("failed-policy-001")
    assert failed_record["status"] == "FAILED"
    assert failed_record["generation"]["policy"]["runtime_policy_snapshot"]


def test_policy_summary_survives_sql_restart() -> None:
    factory = sqlite_chat_session_factory()
    first_store = SqlAlchemyChatInteractionStore(factory)
    client, _, _, _, _ = client_with_policy(chat_store=first_store)

    response = client.post(
        "/api/v1/chat/interactions",
        json={"interaction_id": "sql-policy-001", "user_message": "hello"},
        headers=headers(),
    )
    restarted = SqlAlchemyChatInteractionStore(factory)
    loaded = restarted.get("sql-policy-001")

    assert response.status_code == 200
    assert loaded["generation"]["policy"] == response.json()["generation"]["policy"]
    assert len(
        loaded["generation"]["policy"]["generation_policy_package"][
            "client_package_hash"
        ]
    ) == 64


def test_policy_errors_fail_closed_before_generation() -> None:
    client, generation, _, store, _ = client_with_policy()
    forbidden = client.post(
        "/api/v1/chat/interactions",
        json={
            "user_message": "hello",
            "generation": {"api_key": "secret"},
        },
        headers=headers(),
    )

    assert forbidden.status_code == 422
    assert forbidden.json()["error_code"] == "ae.provider_runtime_field_forbidden"
    assert generation.calls == []
    assert store.records == {}

    class FailedPromptStore:
        def get_binding(self, binding_key):
            raise PromptRepositoryError(
                "ae.prompt_registry_unavailable",
                "AE prompt registry is unavailable.",
                True,
            )

    failed, failed_generation, _, _, _ = client_with_policy(
        prompt_store=FailedPromptStore()
    )
    unavailable = failed.post(
        "/api/v1/chat/interactions",
        json={"user_message": "hello"},
        headers=headers(),
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True
    assert failed_generation.calls == []


def test_policy_summary_rejects_partial_lineage() -> None:
    try:
        build_policy_generation_summary(
            runtime_policy={"policy": "value"},
            prompt_binding=None,
            prompt_render_event=None,
        )
    except ChatInteractionError as exc:
        assert exc.error_code == "ae.runtime_policy_summary_incomplete"
    else:
        raise AssertionError("expected incomplete policy summary rejection")


def sqlite_chat_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_chat_interactions (
                chat_interaction_id TEXT PRIMARY KEY,
                interaction_schema_version TEXT NOT NULL,
                workspace_id TEXT, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                chat_document_id TEXT NOT NULL, status TEXT NOT NULL,
                trace_id TEXT NOT NULL, request_id TEXT NOT NULL,
                user_message_hash TEXT NOT NULL, user_message_preview TEXT NOT NULL,
                cx_retrieval_package_id TEXT, cx_retrieval_package_hash TEXT,
                cx_generation_id TEXT, cx_generation_status TEXT,
                retrieval_summary TEXT NOT NULL, generation_summary TEXT NOT NULL,
                failure_summary TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE ae_chat_artifact_refs (
                chat_artifact_ref_id TEXT PRIMARY KEY,
                chat_interaction_id TEXT NOT NULL, chat_document_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL, artifact_version_id TEXT NOT NULL,
                display_title TEXT NOT NULL, artifact_type TEXT NOT NULL,
                artifact_status TEXT NOT NULL, primary_format TEXT NOT NULL,
                available_formats TEXT NOT NULL, preview_route TEXT,
                download_routes TEXT NOT NULL, source_generation_id TEXT NOT NULL,
                source_content_hash TEXT NOT NULL, quality_summary TEXT NOT NULL,
                actions TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (chat_interaction_id, artifact_id, artifact_version_id)
            )
        """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
