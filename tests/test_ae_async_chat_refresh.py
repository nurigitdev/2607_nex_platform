from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nex_ae_api.chat import (
    ChatInteractionStore,
    SqlAlchemyChatInteractionStore,
    register_chat_routes,
)
from nex_ae_api.generated_response_storage import InMemoryGeneratedResponseStorage
from nex_ae_api.generated_response_storage import GeneratedResponseStorageError
from nex_ae_api.prompts import seed_ae_prompt_registry
from nex_ae_api.workspace import WorkspaceStateStore
from nex_runtime import (
    SERVICE_SPECS,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.prompts import PromptRegistryStore


class SyncClient:
    def create_generation(self, *args, **kwargs):
        raise AssertionError("sync generation is not expected")


class RetrievalClient:
    def create_retrieval_context(self, *args, **kwargs):
        raise AssertionError("retrieval is not expected")


class AsyncLifecycleClient:
    def __init__(self) -> None:
        self.job_status = "QUEUED"
        self.handoff_status = "PENDING"
        self.content = "Owner result [1]."
        self.handoff_calls = []

    def admit_generation(self, payload, **kwargs):
        return {
            "admission_status": "ENQUEUED",
            "job": self._job(),
            "generation": None,
        }

    def get_handoff(self, job_id, **kwargs):
        self.handoff_calls.append({"job_id": job_id, **kwargs})
        content = None
        generation = None
        next_action = {
            "PENDING": "POLL_GENERATION_JOB",
            "READY": "PRESENT_GENERATION_TO_OWNER",
            "BLOCKED": "RETRY_OR_REPAIR_GENERATION",
        }[self.handoff_status]
        if self.handoff_status == "READY":
            encoded = self.content.encode()
            generation = {
                "cx_generation_id": "cx-refresh-1",
                "status": "COMPLETED",
                "request_metadata": {
                    "grounding_required": True,
                    "retrieval_package_id": "retrieval-refresh-1",
                    "retrieval_package_hash": "a" * 64,
                    "structured_draft_id": "draft-refresh-1",
                    "draft_validation_status": "VALIDATED",
                    "grounded_response_quality_audit_schema_version": (
                        "cx_grounded_response_citation_quality_audit.v1"
                    ),
                    "grounded_response_quality_status": "PASS",
                    "grounded_response_quality_issue_count": 0,
                    "citation_repair": {
                        "repair_schema_version": "cx_citation_repair.v1",
                        "attempted": True,
                        "attempt_count": 1,
                        "max_attempts": 1,
                        "trigger_error_code": "cx.citation_required_missing",
                        "same_retrieval_package": True,
                        "original_provider_prompt_package_hash": "b" * 64,
                        "effective_provider_prompt_package_hash": "c" * 64,
                        "invalid_output_included": False,
                    },
                },
            }
            content = {
                "cx_generation_id": "cx-refresh-1",
                "content_type": "text/plain; charset=utf-8",
                "content": self.content,
                "content_sha256": hashlib.sha256(encoded).hexdigest(),
                "size_bytes": len(encoded),
                "owner_scope_enforced": True,
            }
        return {
            "handoff_schema_version": "cx_generation_handoff.v1",
            "handoff_status": self.handoff_status,
            "next_action": next_action,
            "job": self._job(),
            "generation": generation,
            "content": content,
            "owner_scope_enforced": True,
        }

    def get_job(self, *args, **kwargs):
        raise AssertionError("handoff is the canonical refresh")

    def cancel_job(self, *args, **kwargs):
        raise AssertionError("cancel is not expected")

    def _job(self):
        error = None
        if self.job_status in {"FAILED", "CANCELLED"}:
            error = {
                "error_code": "cx.async_generation.failed",
                "retryable": self.job_status == "FAILED",
                "dead_lettered": self.job_status == "FAILED",
            }
        return {
            "async_generation_schema_version": "cx_async_generation_job.v1",
            "job_id": "job-refresh-1",
            "cx_generation_id": "cx-refresh-1",
            "status": self.job_status,
            "attempt_count": 1,
            "max_attempts": 3,
            "retryable": self.job_status != "CANCELLED",
            "available_at": None,
            "created_at": "2026-09-28T00:00:00Z",
            "updated_at": "2026-09-28T00:00:01Z",
            "links": {
                "generation": "/api/v1/generations/cx-refresh-1",
                "async_job": "/api/v1/generation-jobs/job-refresh-1",
            },
            "error": error,
        }


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-oa", audience="nex-ae-api")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-refresh",
        "traceparent": (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ),
    }


def _client(
    store=None,
    asynchronous=None,
    event_emitter=None,
    response_storage=None,
):
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    prompts = PromptRegistryStore()
    seed_ae_prompt_registry(prompts)
    store = store or ChatInteractionStore()
    asynchronous = asynchronous or AsyncLifecycleClient()
    register_chat_routes(
        app,
        store=store,
        cx_client=SyncClient(),
        cx_async_client=asynchronous,
        retrieval_client=RetrievalClient(),
        prompt_store=prompts,
        event_emitter=event_emitter,
        generated_response_storage=response_storage,
    )
    return TestClient(app), store, asynchronous


def _admit(client: TestClient, interaction_id: str = "refresh-1"):
    return client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": interaction_id,
            "user_message": "private question",
            "generation": {"execution_strategy": "ASYNCHRONOUS"},
        },
        headers=_headers(),
    )


def test_pending_refresh_updates_attempts_without_exposing_content() -> None:
    client, store, asynchronous = _client()
    assert _admit(client).status_code == 202
    asynchronous.job_status = "RUNNING"

    response = client.post(
        "/api/v1/chat/interactions/refresh-1/refresh", headers=_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interaction"]["status"] == "PENDING"
    assert body["result"]["handoff_status"] == "PENDING"
    assert body["result"]["content"] is None
    assert body["content_persisted_by_ae"] is False
    assert store.get("refresh-1")["generation"]["async_generation"][
        "attempt_count"
    ] == 1
    assert asynchronous.handoff_calls[0]["tenant_id"] == "local-tenant"
    assert asynchronous.handoff_calls[0]["subject_id"] == "local-user"


def test_ready_refresh_persists_private_content_and_safe_projection() -> None:
    client, store, asynchronous = _client()
    _admit(client, "ready-1")
    asynchronous.job_status = "SUCCEEDED"
    asynchronous.handoff_status = "READY"

    response = client.post(
        "/api/v1/chat/interactions/ready-1/refresh", headers=_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interaction"]["status"] == "COMPLETED"
    assert body["result"]["content"] == "Owner result [1]."
    assert body["result"]["content_sha256"] == hashlib.sha256(
        b"Owner result [1]."
    ).hexdigest()
    assert body["content_persisted_by_ae"] is True
    persisted = store.get("ready-1")
    assert persisted["generation"]["async_generation"]["handoff_status"] == "READY"
    assert persisted["generation"]["citation_workflow"]["workflow_status"] == (
        "REPAIRED"
    )
    assert persisted["generation"]["citation_workflow"]["content_included"] is False
    assert persisted["generation"]["generated_response"]["content_available"] is True
    assert persisted["generation"]["generated_response"][
        "storage_ref_included"
    ] is False
    assert "Owner result [1]." not in str(persisted)
    assert "ae://chat-responses/" not in str(persisted)
    assert persisted["failure"] is None

    owner_response = client.get(
        "/api/v1/chat/interactions/ready-1/response", headers=_headers()
    )
    assert owner_response.status_code == 200
    assert owner_response.json()["content"] == "Owner result [1]."

    repeated = client.post(
        "/api/v1/chat/interactions/ready-1/refresh", headers=_headers()
    )
    assert repeated.status_code == 200
    assert repeated.json()["interaction"]["generation"]["generated_response"][
        "response_id"
    ] == persisted["generation"]["generated_response"]["response_id"]


def test_ready_citation_workflow_survives_sql_restart_without_second_cx_call() -> None:
    factory = _sqlite_chat_session_factory()
    first_store = SqlAlchemyChatInteractionStore(factory)
    asynchronous = AsyncLifecycleClient()
    response_storage = InMemoryGeneratedResponseStorage()
    client, _, _ = _client(
        store=first_store,
        asynchronous=asynchronous,
        response_storage=response_storage,
    )
    _admit(client, "durable-citation-1")
    asynchronous.job_status = "SUCCEEDED"
    asynchronous.handoff_status = "READY"

    refreshed = client.post(
        "/api/v1/chat/interactions/durable-citation-1/refresh",
        headers=_headers(),
    )
    restarted_store = SqlAlchemyChatInteractionStore(factory)
    restarted_client, _, _ = _client(
        store=restarted_store,
        asynchronous=asynchronous,
        response_storage=response_storage,
    )
    citation = restarted_client.get(
        "/api/v1/chat/interactions/durable-citation-1/citation-quality",
        headers=_headers(),
    )
    owner_response = restarted_client.get(
        "/api/v1/chat/interactions/durable-citation-1/response",
        headers=_headers(),
    )

    assert refreshed.status_code == 200
    assert citation.status_code == 200
    assert owner_response.status_code == 200
    assert owner_response.json()["content"] == "Owner result [1]."
    assert citation.json()["workflow_status"] == "REPAIRED"
    assert len(asynchronous.handoff_calls) == 1
    loaded = restarted_store.get("durable-citation-1")
    assert loaded["generation"]["citation_workflow"] == citation.json()
    assert loaded["generation"]["generated_response"]["content_available"] is True
    assert "Owner result [1]." not in str(loaded)


def test_ready_refresh_emits_metadata_only_citation_workflow_event() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ae-api", store=event_store)
    client, _, asynchronous = _client(event_emitter=emitter)
    _admit(client, "observed-citation-1")
    asynchronous.job_status = "SUCCEEDED"
    asynchronous.handoff_status = "READY"

    response = client.post(
        "/api/v1/chat/interactions/observed-citation-1/refresh",
        headers=_headers(),
    )

    events = event_store.list_events(
        event_type="ae.citation_quality.workflow_observed"
    )
    response_events = event_store.list_events(
        event_type="ae.generated_response.persisted"
    )
    assert response.status_code == 200
    assert len(events) == 1
    assert events[0]["details"]["outcome"] == "BOUNDED_REPAIR_SUCCEEDED"
    assert events[0]["details"]["response_content_included"] is False
    assert "Owner result [1]." not in str(events)
    assert len(response_events) == 1
    assert response_events[0]["details"]["content_available"] is True
    assert response_events[0]["details"]["bounded_repair_applied"] is True
    assert response_events[0]["details"]["response_content_included"] is False
    assert "Owner result [1]." not in str(response_events)


class FailingResponseStorage(InMemoryGeneratedResponseStorage):
    def save(self, payload):
        raise GeneratedResponseStorageError(
            error_code="ae.generated_response_storage_unavailable",
            detail="AE generated response storage is unavailable.",
            retryable=True,
        )


def test_ready_refresh_fails_closed_when_private_storage_is_unavailable() -> None:
    client, store, asynchronous = _client(
        response_storage=FailingResponseStorage()
    )
    _admit(client, "storage-failure-1")
    asynchronous.job_status = "SUCCEEDED"
    asynchronous.handoff_status = "READY"

    response = client.post(
        "/api/v1/chat/interactions/storage-failure-1/refresh", headers=_headers()
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == (
        "ae.generated_response_storage_unavailable"
    )
    persisted = store.get("storage-failure-1")
    assert persisted["status"] == "PENDING"
    assert "generated_response" not in persisted["generation"]


def test_blocked_refresh_persists_safe_failure() -> None:
    client, store, asynchronous = _client()
    _admit(client, "blocked-1")
    asynchronous.job_status = "FAILED"
    asynchronous.handoff_status = "BLOCKED"

    response = client.post(
        "/api/v1/chat/interactions/blocked-1/refresh", headers=_headers()
    )

    assert response.status_code == 200
    assert response.json()["interaction"]["status"] == "FAILED"
    failure = store.get("blocked-1")["failure"]
    assert failure["error_code"] == "cx.async_generation.failed"
    assert failure["retryable"] is True
    assert failure["raw_error_detail_included"] is False


def test_workspace_async_admission_and_refresh_append_safe_activity() -> None:
    client, _, asynchronous = _client()
    workspace_store = WorkspaceStateStore()
    workspace = workspace_store.create_workspace(
        payload={
            "workspace_id": "workspace-async-refresh",
            "tenant_id": "local-tenant",
            "owner_user_id": "local-user",
        },
        request_id="request-workspace",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    )
    client.app.state.ae_workspace_store = workspace_store
    admitted = client.post(
        "/api/v1/chat/interactions",
        json={
            "interaction_id": "workspace-async-1",
            "workspace_id": workspace["workspace_id"],
            "user_message": "private workspace question",
            "generation": {"execution_strategy": "ASYNCHRONOUS"},
        },
        headers=_headers(),
    )
    asynchronous.job_status = "RUNNING"
    refreshed = client.post(
        "/api/v1/chat/interactions/workspace-async-1/refresh",
        headers=_headers(),
    )

    assert admitted.status_code == 202
    assert refreshed.status_code == 200
    activities = workspace_store.list_activities(workspace["workspace_id"])
    assert [activity["activity_type"] for activity in activities] == [
        "workspace.created",
        "chat.interaction.started",
        "chat.async.admitted",
        "chat.async.refreshed",
    ]
    assert activities[-1]["metadata"]["async_job_status"] == "RUNNING"
    assert "private workspace question" not in str(activities)


def test_refresh_rejects_missing_and_synchronous_interactions() -> None:
    client, store, _ = _client()
    missing = client.post(
        "/api/v1/chat/interactions/missing/refresh", headers=_headers()
    )
    assert missing.status_code == 404

    store.save(
        {
            "interaction_id": "sync-1",
            "tenant_id": "local-tenant",
            "owner_user_id": "local-user",
            "generation": {"policy": {}},
        }
    )
    synchronous = client.post(
        "/api/v1/chat/interactions/sync-1/refresh", headers=_headers()
    )
    assert synchronous.status_code == 409
    assert synchronous.json()["error_code"] == (
        "ae.async_generation.interaction_invalid"
    )


def test_refresh_rejects_tampered_ready_content_without_mutating_record() -> None:
    client, store, asynchronous = _client()
    _admit(client, "tampered-1")
    asynchronous.job_status = "SUCCEEDED"
    asynchronous.handoff_status = "READY"
    original = asynchronous.get_handoff

    def tampered(*args, **kwargs):
        value = original(*args, **kwargs)
        value["content"]["content_sha256"] = "0" * 64
        return value

    asynchronous.get_handoff = tampered
    response = client.post(
        "/api/v1/chat/interactions/tampered-1/refresh", headers=_headers()
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "ae.async_generation.contract_invalid"
    assert store.get("tampered-1")["status"] == "PENDING"


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
