from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import nex_ae_api.upload_progress as progress
from nex_ae_api.upload_handoff_persistence import UploadHandoffRepositoryError
from nex_ae_api.upload_progress import (
    HttpCxUploadProgressClient,
    UploadProgressError,
    build_default_cx_upload_progress_client,
    build_upload_progress_projection,
    load_upload_progress,
    register_upload_progress_routes,
)
from nex_ae_api.uploads import UploadHandoffStore
from nex_runtime import (
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "request-1348"
VECTOR_ID = "11111111-1111-4111-8111-111111111111"
ROOT = Path(__file__).resolve().parents[1]


def _handoff(**overrides: object) -> dict[str, Any]:
    value = {
        "upload_handoff_id": "handoff-1348",
        "workspace_id": "workspace-1348",
        "tenant_id": "tenant-a",
        "owner_user_id": "owner-a",
        "cx_document_ref": {
            "document_id": "document-1348",
            "upload_id": "upload-1348",
            "ingestion_job_id": "job-1348",
        },
    }
    value.update(overrides)
    return value


def _run(
    *,
    status: str = "SUCCEEDED",
    vector_output: str | None = f"cx.vector_index:{VECTOR_ID}",
    last_error: dict[str, Any] | None = None,
    retry_at: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": "run-1348",
        "document_id": "document-1348",
        "job_id": "job-1348",
        "status": status,
        "current_step": None if status == "SUCCEEDED" else "embedding_index",
        "attempt_count": 2,
        "max_attempts": 4,
        "checkpoint_version": 7,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "lease_expires_at": None,
        "retry_at": retry_at,
        "last_error": last_error,
        "created_at": "2026-10-05T01:00:00Z",
        "updated_at": "2026-10-05T01:01:00Z",
        "completed_at": "2026-10-05T01:01:00Z" if status == "SUCCEEDED" else None,
        "step_total": 4,
        "step_completed": 4 if status == "SUCCEEDED" else 2,
        "steps": [
            {
                "step_id": "embedding_index",
                "status": "SUCCEEDED" if vector_output else "RUNNING",
                "attempt_count": 1,
                "output_ref": vector_output,
                "error_code": None,
                "started_at": "2026-10-05T01:00:00Z",
                "completed_at": "2026-10-05T01:01:00Z" if vector_output else None,
            }
        ],
    }


def _collection(*runs: dict[str, Any]) -> dict[str, Any]:
    return {
        "read_model_schema_version": "cx_ingestion_run_read_model.v1",
        "document_id": "document-1348",
        "run_count": len(runs),
        "status_counts": {},
        "runs": list(runs),
    }


def _readiness(**overrides: object) -> dict[str, Any]:
    value = {
        "readiness_schema_version": "cx_vector_index_readiness.v1",
        "vector_index_id": VECTOR_ID,
        "content_object_id": "document-1348",
        "status": "READY",
        "status_reason": None,
        "freshness_status": "READY",
        "freshness_reason": None,
        "checkpoint_version": 1,
        "expected_vector_count": 3,
        "actual_vector_count": 3,
        "retrieval_usable": True,
        "rebuild_required": False,
        "action": "NONE",
    }
    value.update(overrides)
    return value


class FakeCxProgressClient:
    def __init__(self, runs=None, readiness=None, error=None) -> None:
        self.runs = runs if runs is not None else _collection(_run())
        self.readiness = _readiness() if readiness is None else readiness
        self.error = error
        self.calls: list[str] = []

    def list_ingestion_runs(self, document_id: str, **kwargs: object):
        self.calls.append(
            f"runs:{document_id}:{kwargs['tenant_id']}:{kwargs['owner_user_id']}"
        )
        if self.error is not None:
            raise self.error
        return deepcopy(self.runs)

    def get_vector_readiness(self, vector_index_id: str, **kwargs: object):
        self.calls.append(f"vector:{vector_index_id}")
        return deepcopy(self.readiness)


def _headers(*, owner: str = "owner-a") -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id="tenant-a",
        user_id=owner,
        scopes=[DEFAULT_USER_SCOPE],
        roles=["employee"],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _client(*, store=None, cx_client=None):
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    selected_store = store or UploadHandoffStore()
    selected_store.save(_handoff())
    selected_cx = cx_client or FakeCxProgressClient()
    register_upload_progress_routes(
        app,
        upload_store=selected_store,
        cx_client=selected_cx,
    )
    return TestClient(app), selected_cx


def test_progress_route_returns_owner_scoped_index_ready_projection() -> None:
    client, cx_client = _client()

    response = client.get(
        "/api/v1/uploads/handoff-1348/progress",
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["progress_schema_version"] == "ae_upload_ingestion_progress.v1"
    assert payload["status"] == "INDEX_READY"
    assert payload["progress_percent"] == 100
    assert payload["vector_index"]["freshness_status"] == "READY"
    assert payload["vector_index"]["retrieval_usable"] is True
    assert payload["metadata"] == {
        "owner_scoped": True,
        "raw_source_included": False,
        "markdown_included": False,
        "chunk_text_included": False,
        "embedding_vector_included": False,
        "provider_credentials_included": False,
    }
    assert cx_client.calls == [
        "runs:document-1348:tenant-a:owner-a",
        f"vector:{VECTOR_ID}",
    ]


def test_progress_route_requires_auth_and_hides_other_owner() -> None:
    client, cx_client = _client()

    unauthorized = client.get("/api/v1/uploads/handoff-1348/progress")
    hidden = client.get(
        "/api/v1/uploads/handoff-1348/progress",
        headers=_headers(owner="owner-b"),
    )

    assert unauthorized.status_code == 401
    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "ae.upload_progress_not_found"
    assert cx_client.calls == []


def test_progress_route_uses_oa_session_client_in_protected_mode() -> None:
    class FakeOaSessionClient:
        def introspect_session(
            self, session_id: str, **kwargs: object
        ) -> dict[str, Any]:
            assert session_id == "oa-session-1348"
            return {
                "active": True,
                "inactive_reason": None,
                "session": {
                    "browser_session_schema_version": "oa_browser_session.v1",
                    "session_id": session_id,
                    "status": "ACTIVE",
                    "issuer": "nex-oa",
                    "audience": "nex-ae-api",
                    "token_use": "user",
                    "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
                    "subject_ref": {"type": "oa.user", "id": "owner-a"},
                    "scopes": ["workspace:use"],
                    "roles": ["employee"],
                    "issued_at": "2026-10-05T00:00:00Z",
                    "expires_at": "2026-10-05T02:00:00Z",
                    "auth_time": "2026-10-05T00:00:00Z",
                },
            }

    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = UploadHandoffStore()
    store.save(_handoff())
    cx_client = FakeCxProgressClient()
    register_upload_progress_routes(
        app,
        upload_store=store,
        cx_client=cx_client,
        oa_session_client=FakeOaSessionClient(),
        session_mode="oa",
    )
    client = TestClient(app)
    client.cookies.set("nex_ae_user_session", "oa-session-1348")

    response = client.get("/api/v1/uploads/handoff-1348/progress")

    assert response.status_code == 200
    assert response.json()["status"] == "INDEX_READY"
    assert cx_client.calls[0] == "runs:document-1348:tenant-a:owner-a"


def test_progress_projects_queued_waiting_failure_and_cancelled_states() -> None:
    queued = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=None,
        vector_index_id=None,
        readiness=None,
    )
    error = {
        "error_code": "cx.embedding.timeout",
        "failed_step": "embedding_index",
        "retryable": True,
        "failed_at": "2026-10-05T01:01:00Z",
    }
    waiting = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=_run(
            status="WAITING_RETRY",
            vector_output=None,
            last_error=error,
            retry_at="2026-10-05T01:02:00Z",
        ),
        vector_index_id=None,
        readiness=None,
    )
    failed = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=_run(
            status="FAILED",
            vector_output=None,
            last_error={**error, "retryable": False},
        ),
        vector_index_id=None,
        readiness=None,
    )
    cancelled = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=_run(status="CANCELLED", vector_output=None),
        vector_index_id=None,
        readiness=None,
    )

    assert queued["status"] == "QUEUED"
    assert queued["progress_percent"] == 0
    assert waiting["status"] == "WAITING_RETRY"
    assert waiting["progress_percent"] == 50
    assert waiting["failure"]["error_code"] == "cx.embedding.timeout"
    assert waiting["retry"] == {
        "available": True,
        "retry_at": "2026-10-05T01:02:00Z",
        "attempts_remaining": 2,
    }
    assert failed["status"] == "FAILED"
    assert failed["retry"]["available"] is False
    assert cancelled["status"] == "CANCELLED"


def test_succeeded_without_fresh_payload_is_not_index_ready() -> None:
    missing = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=_run(),
        vector_index_id=VECTOR_ID,
        readiness=None,
    )
    stale = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=_run(),
        vector_index_id=VECTOR_ID,
        readiness=_readiness(
            freshness_status="STALE",
            freshness_reason="PAYLOAD_COUNT_MISMATCH",
            retrieval_usable=False,
            rebuild_required=True,
            actual_vector_count=2,
        ),
    )

    assert missing["status"] == "INDEX_NOT_READY"
    assert missing["vector_index"]["freshness_reason"] == "INDEX_NOT_FOUND"
    assert stale["status"] == "INDEX_NOT_READY"
    assert stale["vector_index"]["rebuild_required"] is True
    assert stale["vector_index"]["actual_vector_count"] == 2


def test_load_progress_skips_readiness_until_embedding_output_exists() -> None:
    client = FakeCxProgressClient(runs=_collection(_run(status="RUNNING", vector_output=None)))

    payload = load_upload_progress(
        _handoff(),
        client=client,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert payload["status"] == "PROCESSING"
    assert payload["vector_index"]["freshness_reason"] == "INDEX_NOT_PUBLISHED"
    assert client.calls == ["runs:document-1348:tenant-a:owner-a"]


def test_empty_runs_and_non_embedding_steps_remain_queued_without_vector_call() -> None:
    empty_client = FakeCxProgressClient(runs=_collection())
    empty = load_upload_progress(
        _handoff(),
        client=empty_client,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    run = _run(status="QUEUED", vector_output=None)
    run["steps"] = [
        "ignored",
        {
            "step_id": "chunking",
            "output_ref": "cx.chunk_set:value",
        },
    ]
    no_embedding_client = FakeCxProgressClient(runs=_collection(run))
    no_embedding = load_upload_progress(
        _handoff(),
        client=no_embedding_client,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert empty["status"] == "QUEUED"
    assert empty_client.calls == ["runs:document-1348:tenant-a:owner-a"]
    assert no_embedding["status"] == "QUEUED"
    assert no_embedding_client.calls == ["runs:document-1348:tenant-a:owner-a"]


def test_projection_bounds_progress_and_attempts_and_rejects_bad_handoff() -> None:
    running = _run(status="RUNNING", vector_output=None)
    running["step_completed"] = 4
    running["attempt_count"] = 6
    running["max_attempts"] = 4
    projection = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=running,
        vector_index_id=None,
        readiness=None,
    )
    unknown = _run(status="UNKNOWN", vector_output=None)
    unknown_projection = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=unknown,
        vector_index_id=None,
        readiness=None,
    )

    assert projection["progress_percent"] == 99
    assert projection["retry"]["attempts_remaining"] == 0
    assert unknown_projection["status"] == "QUEUED"
    with pytest.raises(UploadProgressError):
        build_upload_progress_projection(
            handoff=_handoff(cx_document_ref=None),
            latest_run=None,
            vector_index_id=None,
            readiness=None,
        )
    with pytest.raises(UploadProgressError):
        build_upload_progress_projection(
            handoff=_handoff(workspace_id=" "),
            latest_run=None,
            vector_index_id=None,
            readiness=None,
        )


@pytest.mark.parametrize(
    "collection",
    [
        {"document_id": "other", "runs": []},
        {"document_id": "document-1348", "runs": {}},
        {"document_id": "document-1348", "runs": ["bad"]},
        {"document_id": "document-1348", "runs": [{"document_id": "other"}]},
    ],
)
def test_load_progress_rejects_invalid_run_collection(collection) -> None:
    client = FakeCxProgressClient(runs=collection)
    with pytest.raises(UploadProgressError) as exc_info:
        load_upload_progress(
            _handoff(),
            client=client,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert exc_info.value.error_code == "ae.upload_progress_dependency_invalid"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda run: run.update(steps={}),
        lambda run: run["steps"][0].update(output_ref="wrong:index"),
        lambda run: run.update(step_total=-1),
    ],
)
def test_load_progress_rejects_invalid_run_metadata(mutation) -> None:
    run = _run()
    mutation(run)
    with pytest.raises(UploadProgressError) as exc_info:
        load_upload_progress(
            _handoff(),
            client=FakeCxProgressClient(runs=_collection(run)),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert exc_info.value.status_code == 502


def test_load_progress_rejects_invalid_handoff_and_readiness_lineage() -> None:
    with pytest.raises(UploadProgressError) as bad_handoff:
        load_upload_progress(
            _handoff(cx_document_ref=None),
            client=FakeCxProgressClient(),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert bad_handoff.value.status_code == 409

    with pytest.raises(UploadProgressError) as bad_readiness:
        load_upload_progress(
            _handoff(),
            client=FakeCxProgressClient(
                readiness=_readiness(vector_index_id="other")
            ),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert bad_readiness.value.status_code == 502


def test_progress_route_normalizes_cx_and_repository_errors() -> None:
    dependency = UploadProgressError(503, "cx.progress.unavailable", "Unavailable", True)
    client, _ = _client(cx_client=FakeCxProgressClient(error=dependency))
    response = client.get(
        "/api/v1/uploads/handoff-1348/progress",
        headers=_headers(),
    )
    assert response.status_code == 503
    assert response.json()["retryable"] is True

    class BrokenStore(UploadHandoffStore):
        def get(self, *args, **kwargs):
            raise UploadHandoffRepositoryError(
                503,
                "ae.upload_handoff_store_unavailable",
                "Unavailable",
                True,
            )

    broken = BrokenStore()
    broken.save(_handoff())
    repository_client, _ = _client(store=broken)
    unavailable = repository_client.get(
        "/api/v1/uploads/handoff-1348/progress",
        headers=_headers(),
    )
    assert unavailable.status_code == 503


def test_http_client_propagates_owner_headers_and_normalizes_responses(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: float):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        if url.endswith("/readiness"):
            return httpx.Response(404, json={"error_code": "not_found"})
        return httpx.Response(200, json=_collection(_run()))

    monkeypatch.setattr(progress.httpx, "get", fake_get)
    client = HttpCxUploadProgressClient(base_url="http://cx", service_token="token")
    assert client.list_ingestion_runs(
        "document-1348",
        tenant_id="tenant-a",
        owner_user_id="owner-a",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )["run_count"] == 1
    assert client.get_vector_readiness(
        VECTOR_ID,
        tenant_id="tenant-a",
        owner_user_id="owner-a",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    ) is None
    assert calls[0]["headers"]["X-NEX-Tenant-ID"] == "tenant-a"
    assert calls[0]["headers"]["X-NEX-Subject-ID"] == "owner-a"
    assert calls[0]["headers"]["Authorization"] == "Bearer token"


def test_default_http_client_reads_service_configuration(monkeypatch) -> None:
    monkeypatch.setenv("NEX_CX_BASE_URL", "http://cx-configured")
    monkeypatch.setenv("NEX_AE_TO_CX_SERVICE_TOKEN", "configured-token")

    client = build_default_cx_upload_progress_client()

    assert client.base_url == "http://cx-configured"
    assert client.service_token == "configured-token"


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(503, json={"error_code": "cx.down", "retryable": True}), "cx.down"),
        (httpx.Response(502, content=b"not-json"), "cx.upload_progress_request_failed"),
        (httpx.Response(200, json=[]), "ae.upload_progress_dependency_invalid"),
    ],
)
def test_http_client_rejects_dependency_failures(monkeypatch, response, expected_code) -> None:
    monkeypatch.setattr(progress.httpx, "get", lambda *args, **kwargs: response)
    with pytest.raises(UploadProgressError) as exc_info:
        HttpCxUploadProgressClient(
            base_url="http://cx",
            service_token="token",
        ).list_ingestion_runs(
            "document-1348",
            tenant_id="tenant-a",
            owner_user_id="owner-a",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )
    assert exc_info.value.error_code == expected_code
    assert str(exc_info.value)


def test_progress_projection_excludes_private_payload_keys() -> None:
    projection = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=_run(),
        vector_index_id=VECTOR_ID,
        readiness=_readiness(),
    )
    serialized = json.dumps(projection, sort_keys=True).lower()
    for forbidden in (
        '"content_text"',
        '"content_base64"',
        '"chunk_text"',
        '"embedding"',
        '"vector"',
        '"api_key"',
        '"access_token"',
    ):
        assert forbidden not in serialized


def test_progress_projection_matches_strict_contract() -> None:
    schema = json.loads(
        (
            ROOT
            / "contracts"
            / "schemas"
            / "service"
            / "nex_ae_api"
            / "upload_ingestion_progress.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    projection = build_upload_progress_projection(
        handoff=_handoff(),
        latest_run=_run(),
        vector_index_id=VECTOR_ID,
        readiness=_readiness(),
    )

    Draft202012Validator(schema).validate(projection)
