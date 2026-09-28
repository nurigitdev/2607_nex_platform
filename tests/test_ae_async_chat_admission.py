from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_ae_api.chat import (
    ChatInteractionStore,
    SqlAlchemyChatInteractionStore,
    register_chat_routes,
)
from nex_ae_api.cx_async_generation_client import CxAsyncGenerationClientError
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from nex_runtime.prompts import PromptRegistryStore


class UnexpectedSyncClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_generation(self, payload, *, request_id, trace_id):
        self.calls.append(payload)
        raise AssertionError("synchronous CX generation must not be called")


class UnexpectedRetrievalClient:
    def create_retrieval_context(self, payload, *, request_id, trace_id):
        raise AssertionError("general async chat must not retrieve")


class RecordingAsyncClient:
    def __init__(self, *, status: str = "QUEUED", fail: bool = False) -> None:
        self.status = status
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def admit_generation(
        self, payload, *, request_id, trace_id, idempotency_key
    ):
        self.calls.append(
            {
                "payload": payload,
                "request_id": request_id,
                "trace_id": trace_id,
                "idempotency_key": idempotency_key,
            }
        )
        if self.fail:
            raise CxAsyncGenerationClientError(
                503, "cx.async_generation.unavailable", "unavailable", True
            )
        return {
            "admission_status": "ENQUEUED",
            "job": {
                "async_generation_schema_version": "cx_async_generation_job.v1",
                "job_id": "job-async-1",
                "cx_generation_id": "cx-async-1",
                "status": self.status,
                "attempt_count": 0,
                "max_attempts": 3,
                "retryable": True,
                "available_at": None,
                "created_at": "2026-09-28T00:00:00Z",
                "updated_at": "2026-09-28T00:00:00Z",
                "links": {
                    "generation": "/api/v1/generations/cx-async-1",
                    "async_job": "/api/v1/generation-jobs/job-async-1",
                },
                "error": None,
            },
            "generation": None,
        }

    def get_job(self, *args, **kwargs):
        raise AssertionError("not used during admission")

    def get_handoff(self, *args, **kwargs):
        raise AssertionError("not used during admission")

    def cancel_job(self, *args, **kwargs):
        raise AssertionError("not used during admission")


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-async-admission",
        "traceparent": (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ),
    }


def _client(*, store=None, async_client=None):
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    prompts = PromptRegistryStore()
    seed_ae_prompt_registry(prompts)
    chats = store or ChatInteractionStore()
    asynchronous = async_client or RecordingAsyncClient()
    synchronous = UnexpectedSyncClient()
    register_chat_routes(
        app,
        store=chats,
        cx_client=synchronous,
        cx_async_client=asynchronous,
        retrieval_client=UnexpectedRetrievalClient(),
        prompt_store=prompts,
    )
    return TestClient(app), chats, asynchronous, synchronous


def _request(interaction_id: str = "async-interaction-1") -> dict:
    return {
        "interaction_id": interaction_id,
        "user_message": "private async question",
        "generation": {"execution_strategy": "ASYNCHRONOUS"},
    }


def test_async_chat_admission_persists_owner_safe_pending_projection() -> None:
    client, store, asynchronous, synchronous = _client()

    response = client.post(
        "/api/v1/chat/interactions", json=_request(), headers=_headers()
    )

    assert response.status_code == 202
    body = response.json()
    projection = body["generation"]["async_generation"]
    assert body["status"] == "PENDING"
    assert body["cx_generation_id"] == "cx-async-1"
    assert body["cx_status"] == "QUEUED"
    assert projection["job_id"] == "job-async-1"
    assert projection["content_included"] is False
    assert body["generation"]["policy"]["generation_policy_package"]
    assert "private async question" not in str(projection)
    assert store.get("async-interaction-1") == body
    assert asynchronous.calls[0]["idempotency_key"] == (
        "ae-chat:async-interaction-1"
    )
    assert synchronous.calls == []


def test_async_chat_replay_returns_existing_without_second_admission() -> None:
    client, _, asynchronous, _ = _client()

    first = client.post(
        "/api/v1/chat/interactions", json=_request(), headers=_headers()
    )
    replay = client.post(
        "/api/v1/chat/interactions", json=_request(), headers=_headers()
    )

    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert len(asynchronous.calls) == 1


def test_async_admission_failure_persists_failed_attempt() -> None:
    client, store, _, _ = _client(async_client=RecordingAsyncClient(fail=True))

    response = client.post(
        "/api/v1/chat/interactions",
        json=_request("async-failed-1"),
        headers=_headers(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "cx.async_generation.unavailable"
    failed = store.get("async-failed-1")
    assert failed["status"] == "FAILED"
    assert failed["failure"]["retryable"] is True
    assert failed["failure"]["raw_error_detail_included"] is False


def test_invalid_execution_strategy_fails_before_pending_persistence() -> None:
    client, store, asynchronous, _ = _client()
    payload = _request("async-invalid-1")
    payload["generation"]["execution_strategy"] = "BACKGROUND_MAGIC"

    response = client.post(
        "/api/v1/chat/interactions", json=payload, headers=_headers()
    )

    assert response.status_code == 400
    assert response.json()["error_code"].endswith("execution_strategy_invalid")
    assert store.get("async-invalid-1") is None
    assert asynchronous.calls == []


def test_terminal_replayed_job_is_persisted_as_failed_projection() -> None:
    client, store, _, _ = _client(
        async_client=RecordingAsyncClient(status="CANCELLED")
    )

    response = client.post(
        "/api/v1/chat/interactions",
        json=_request("async-cancelled-1"),
        headers=_headers(),
    )

    assert response.status_code == 202
    assert response.json()["status"] == "FAILED"
    assert response.json()["generation"]["async_generation"][
        "lifecycle_status"
    ] == "BLOCKED"
    assert store.get("async-cancelled-1")["cx_status"] == "CANCELLED"


def test_async_projection_survives_sql_store_restart() -> None:
    factory = _sqlite_chat_session_factory()
    first_store = SqlAlchemyChatInteractionStore(factory)
    client, _, _, _ = _client(store=first_store)

    response = client.post(
        "/api/v1/chat/interactions",
        json=_request("async-sql-1"),
        headers=_headers(),
    )
    restarted = SqlAlchemyChatInteractionStore(factory)
    loaded = restarted.get("async-sql-1")

    assert response.status_code == 202
    assert loaded["status"] == "PENDING"
    assert loaded["generation"]["async_generation"]["job_id"] == "job-async-1"
    assert loaded["generation"]["policy"]["policy_summary_schema_version"] == (
        "ae_chat_runtime_policy_summary.v1"
    )


def _sqlite_chat_session_factory():
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
