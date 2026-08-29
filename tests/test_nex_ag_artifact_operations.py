from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from nex_ag.artifact_operations import (
    AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION,
    AE_ARTIFACT_SOURCE_SERVICE_ID,
    DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS,
    NEX_AG_AE_ARTIFACT_BASE_URL_ENV,
    NEX_AG_AE_ARTIFACT_SERVICE_TOKEN_ENV,
    NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV,
    AeArtifactOperationsError,
    HttpAeArtifactOperationsClient,
    InMemoryAeArtifactOperationsClient,
    assert_artifact_operation_projection_redacted,
    build_artifact_operation_detail_projection,
    build_default_ae_artifact_operations_client,
    register_artifact_operation_routes,
    summarize_artifact_operation_detail,
)
import nex_ag.artifact_operations as artifact_operations
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
ARTIFACT_ID = "artifact-0409"
HANDOFF_ID = "handoff-0409"
INTERACTION_ID = "interaction-0409"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def artifact_record(*, include_private: bool = True) -> dict[str, Any]:
    record = {
        "artifact_id": ARTIFACT_ID,
        "artifact_schema_version": "ae_artifact_record.v1",
        "artifact_type": "generated_document",
        "artifact_status": "READY",
        "display_title": "Generated report",
        "current_version_id": "version-0409",
        "artifact_request_id": "request-0409",
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "owner_actor_ref": {
            "tenant_id": "tenant-0409",
            "user_id": "user-0409",
            "actor_type": "user",
        },
        "workspace_ref": {
            "workspace_id": "workspace-0409",
            "document_group_id": "group-0409",
            "chat_document_id": "chat-doc-0409",
            "local_path": "/data/nex-platform/private",
        },
        "target_formats": ["MD", "HTML_PREVIEW"],
        "handoff_ref": {
            "artifact_handoff_id": HANDOFF_ID,
            "artifact_request_id": "request-0409",
        },
        "source_refs": [
            {
                "cx_generation_id": "cx-gen-0409",
                "structured_draft_id": "draft-0409",
                "structured_draft_content_hash": "a" * 64,
                "generation_response_hash": "b" * 64,
                "quality_summary": {
                    "citation_status": "VALIDATED",
                    "citation_count": 2,
                    "validation_error_count": 0,
                    "warning_count": 0,
                    "grounding_required": True,
                    "retrieval_package_id": "retrieval-0409",
                    "retrieval_package_hash": "c" * 64,
                    "system_prompt": "SECRET_SYSTEM_PROMPT",
                },
                "raw_source": "raw source text",
            }
        ],
        "versions": [
            {
                "artifact_version_id": "version-0409",
                "artifact_id": ARTIFACT_ID,
                "version_no": 1,
                "version_reason": "initial_render",
                "source_content_hash": "a" * 64,
                "artifact_content_hash": "d" * 64,
                "rendered_formats": ["MD"],
                "validation_snapshot": {"quality_status": "PASS"},
                "created_at": "2026-08-29T00:00:00Z",
            }
        ],
        "render_jobs": [
            {
                "render_job_id": "render-job-0409",
                "artifact_id": ARTIFACT_ID,
                "artifact_version_id": "version-0409",
                "render_status": "SUCCEEDED",
                "renderer_policy_id": "ae-markdown-renderer-v1",
                "target_formats": ["MD"],
                "failure_summary": {},
                "started_at": "2026-08-29T00:00:00Z",
                "completed_at": "2026-08-29T00:00:01Z",
                "created_at": "2026-08-29T00:00:00Z",
            }
        ],
        "files": [
            {
                "artifact_file_id": "file-0409",
                "artifact_version_id": "version-0409",
                "artifact_id": ARTIFACT_ID,
                "format": "MD",
                "mime_type": "text/markdown",
                "file_name": "generated-report.md",
                "file_hash": "e" * 64,
                "file_size_bytes": 128,
                "storage_ref": "ae://artifacts/tenant-0409/file-0409.md",
                "created_at": "2026-08-29T00:00:01Z",
                "content": "PRIVATE_MARKDOWN",
            },
            {
                "artifact_file_id": "unsafe-file-0409",
                "artifact_version_id": "version-0409",
                "artifact_id": ARTIFACT_ID,
                "format": "PDF",
                "mime_type": "application/pdf",
                "file_name": "generated-report.pdf",
                "file_hash": "f" * 64,
                "file_size_bytes": "not-a-number",
                "storage_ref": "/data/nex-platform/ae/private.pdf",
            },
        ],
        "links": [
            {
                "artifact_link_id": "link-0409",
                "artifact_file_id": "file-0409",
                "link_type": "preview",
                "link_route": "/api/v1/artifact-files/file-0409/preview",
                "created_at": "2026-08-29T00:00:01Z",
            },
            {
                "artifact_link_id": "unsafe-link-0409",
                "artifact_file_id": "file-0409",
                "link_type": "download",
                "link_route": "file:///data/nex-platform/ae/private.md",
            },
        ],
        "created_at": "2026-08-29T00:00:00Z",
        "updated_at": "2026-08-29T00:00:01Z",
    }
    if include_private:
        record["source_text"] = "SECRET_SOURCE_TEXT"
    return record


def handoff_record() -> dict[str, Any]:
    return {
        "artifact_handoff_id": HANDOFF_ID,
        "handoff_schema_version": "ae_artifact_handoff.v1",
        "handoff_status": "READY_FOR_RENDERING",
        "artifact_request_id": "request-0409",
        "artifact_intent": "create_and_export",
        "artifact_type": "generated_document",
        "artifact_title": "Generated report",
        "cx_generation_id": "cx-gen-0409",
        "structured_draft_id": "draft-0409",
        "structured_draft_content_hash": "a" * 64,
        "generation_response_hash": "b" * 64,
        "target_formats": ["MD", "HTML_PREVIEW"],
        "quality_summary": {
            "citation_status": "VALIDATED",
            "citation_count": 2,
            "hidden_prompt": "hidden prompt",
        },
        "workspace_ref": {"workspace_id": "workspace-0409"},
        "created_at": "2026-08-29T00:00:00Z",
        "updated_at": "2026-08-29T00:00:01Z",
    }


def chat_artifact_ref() -> dict[str, Any]:
    return {
        "chat_artifact_ref_id": "chat-ref-0409",
        "chat_interaction_id": INTERACTION_ID,
        "chat_document_id": "chat-doc-0409",
        "tenant_id": "tenant-0409",
        "user_id": "user-0409",
        "artifact_id": ARTIFACT_ID,
        "artifact_version_id": "version-0409",
        "display_title": "Generated report",
        "artifact_type": "generated_document",
        "artifact_status": "READY",
        "primary_format": "MD",
        "available_formats": ["MD", "HTML_PREVIEW"],
        "preview_route": "/api/v1/artifact-files/file-0409/preview",
        "download_routes": {
            "MD": "/api/v1/artifact-files/file-0409/download",
            "unsafe": "/data/nex-platform/private",
        },
        "source_generation_id": "cx-gen-0409",
        "source_content_hash": "a" * 64,
        "quality_summary": {"citation_status": "VALIDATED", "citation_count": 2},
        "actions": {"preview": True, "download": True, "unsafe": {"nested": "no"}},
        "created_at": "2026-08-29T00:00:01Z",
        "updated_at": "2026-08-29T00:00:02Z",
    }


def artifact_client() -> InMemoryAeArtifactOperationsClient:
    return InMemoryAeArtifactOperationsClient(
        artifacts={ARTIFACT_ID: artifact_record()},
        handoffs={HANDOFF_ID: handoff_record()},
        chat_artifact_refs={INTERACTION_ID: {"artifact_refs": [chat_artifact_ref()]}},
    )


def test_artifact_operation_projection_summarizes_and_redacts() -> None:
    source_client = artifact_client()
    projection = build_artifact_operation_detail_projection(
        artifact=source_client.get_artifact(
            ARTIFACT_ID,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        ),
        handoff=source_client.get_artifact_handoff(
            HANDOFF_ID,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        ),
        chat_artifact_refs=source_client.list_chat_artifact_refs(
            INTERACTION_ID,
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        ),
        source_client=source_client,
        request_trace_id=TRACE_ID,
    )

    artifact = projection["artifact"]
    assert projection["projection_schema_version"] == (
        AG_ARTIFACT_OPERATION_DETAIL_PROJECTION_SCHEMA_VERSION
    )
    assert projection["projection_status"] == "READY"
    assert projection["summary"] == {
        "artifact_status": "READY",
        "artifact_type": "generated_document",
        "version_count": 1,
        "render_job_count": 1,
        "file_count": 2,
        "link_count": 2,
        "source_ref_count": 1,
        "chat_artifact_ref_count": 1,
        "handoff_loaded": True,
        "latest_render_status": "SUCCEEDED",
    }
    assert artifact["owner_scope"] == {
        "tenant_id": "tenant-0409",
        "user_id": "user-0409",
        "actor_type": "user",
    }
    assert artifact["files"][0]["storage_ref"].startswith("ae://artifacts/")
    assert artifact["files"][1]["storage_ref"] is None
    assert artifact["links"][1]["link_route"] is None
    assert projection["chat_artifact_refs"][0]["download_routes"] == {
        "MD": "/api/v1/artifact-files/file-0409/download"
    }
    assert "SECRET" not in str(projection)
    assert "/data/nex-platform" not in str(projection)


def test_artifact_operation_projection_handles_sparse_values_and_errors() -> None:
    projection = build_artifact_operation_detail_projection(
        artifact={
            "artifact_id": ARTIFACT_ID,
            "artifact_type": "summary",
            "artifact_status": "DRAFT",
            "versions": "not-a-list",
            "render_jobs": "not-a-list",
            "files": "not-a-list",
            "links": "not-a-list",
            "source_refs": "not-a-list",
            "owner_actor_ref": "not-a-mapping",
            "workspace_ref": "not-a-mapping",
        },
        source_errors=[
            AeArtifactOperationsError(
                error_code="ag.ae_artifact_source_request_failed",
                detail="optional handoff failed",
                status_code=503,
            )
        ],
    )

    assert projection["projection_status"] == "DEGRADED"
    assert projection["summary"] == summarize_artifact_operation_detail(
        projection["artifact"],
        None,
        [],
    )
    assert projection["artifact"]["owner_scope"] == {
        "tenant_id": None,
        "user_id": None,
        "actor_type": None,
    }
    assert projection["source_status"]["errors"][0]["status_code"] == 503


def test_artifact_operation_projection_helper_edges() -> None:
    record = artifact_record(include_private=False)
    record["artifact_handoff_id"] = "handoff-top-level"
    record["handoff_ref"] = {"artifact_handoff_id": "handoff-nested"}
    record["source_refs"][0]["quality_summary"] = "not-a-mapping"
    record["versions"][0]["validation_snapshot"] = "not-a-mapping"
    record["render_jobs"][0]["failure_summary"] = "not-a-mapping"
    record["files"].append({"artifact_file_id": "empty-file", "storage_ref": None})
    record["links"].append({"artifact_link_id": "empty-link", "link_route": None})
    ref = chat_artifact_ref()
    ref["download_routes"] = "not-a-mapping"
    ref["actions"] = "not-a-mapping"
    ref["preview_route"] = None

    projection = build_artifact_operation_detail_projection(
        artifact=record,
        chat_artifact_refs=[ref],
    )

    assert projection["artifact"]["artifact_handoff_id"] == "handoff-top-level"
    assert projection["artifact"]["source_refs"][0]["quality_summary"] == {}
    assert projection["artifact"]["versions"][0]["validation_snapshot"] == {}
    assert projection["artifact"]["render_jobs"][0]["failure_summary"] == {}
    assert projection["artifact"]["files"][-1]["storage_ref"] is None
    assert projection["artifact"]["links"][-1]["link_route"] is None
    assert projection["chat_artifact_refs"][0]["download_routes"] == {}
    assert projection["chat_artifact_refs"][0]["actions"] == {}
    assert projection["chat_artifact_refs"][0]["preview_route"] is None
    assert artifact_operations._json_safe_value(["x", {"keep": object(), "drop": None}])[
        1
    ]["keep"].startswith("<object object")


def test_artifact_operation_projection_redaction_guard_raises() -> None:
    with pytest.raises(ValueError, match="private data"):
        assert_artifact_operation_projection_redacted(
            {"artifact": {"storage_ref": "/data/nex-platform/private.md"}}
        )


def test_in_memory_artifact_operations_client_returns_copies_and_missing_values() -> None:
    client = artifact_client()
    artifact = client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    refs = client.list_chat_artifact_refs(
        INTERACTION_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    artifact["artifact_status"] = "MUTATED"
    refs[0]["artifact_status"] = "MUTATED"

    assert client.get_artifact("missing", request_id=REQUEST_ID, trace_id=TRACE_ID) is None
    assert client.get_artifact_handoff("missing", request_id=REQUEST_ID, trace_id=TRACE_ID) is None
    assert client.list_chat_artifact_refs("missing", request_id=REQUEST_ID, trace_id=TRACE_ID) == []
    assert client.artifacts[ARTIFACT_ID]["artifact_status"] == "READY"
    assert client.chat_artifact_refs[INTERACTION_ID]["artifact_refs"][0]["artifact_status"] == "READY"


def build_app(source_client: object) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_artifact_operation_routes(app, client=source_client)
    return TestClient(app)


def test_artifact_operation_route_returns_detail_projection() -> None:
    client = build_app(artifact_client())

    response = client.get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        params={"interaction_id": INTERACTION_ID},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation_type"] == "ae_artifact"
    assert payload["artifact"]["artifact_id"] == ARTIFACT_ID
    assert payload["handoff"]["artifact_handoff_id"] == HANDOFF_ID
    assert payload["chat_artifact_refs"][0]["chat_interaction_id"] == INTERACTION_ID
    assert payload["request_trace_id"] == TRACE_ID


def test_artifact_operation_route_can_disable_optional_reads() -> None:
    client = build_app(artifact_client())

    response = client.get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        params={
            "interaction_id": INTERACTION_ID,
            "include_handoff": "false",
            "include_chat_links": "false",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["handoff"] is None
    assert response.json()["chat_artifact_refs"] == []


def test_artifact_operation_route_auth_filter_missing_and_optional_error_edges() -> None:
    client = build_app(artifact_client())

    unauthorized = client.get(f"/admin/v1/operations/artifacts/{ARTIFACT_ID}")
    invalid_service = client.get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        params={"service_id": "nex-cx"},
        headers=auth_headers(),
    )
    missing = client.get(
        "/admin/v1/operations/artifacts/missing",
        headers=auth_headers(),
    )

    class OptionalFailureClient(InMemoryAeArtifactOperationsClient):
        def get_artifact_handoff(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
            raise AeArtifactOperationsError(
                error_code="ag.optional_handoff_failed",
                detail="handoff unavailable",
            )

        def list_chat_artifact_refs(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            raise AeArtifactOperationsError(
                error_code="ag.optional_chat_links_failed",
                detail="chat links unavailable",
            )

    degraded_client = OptionalFailureClient(
        artifacts={ARTIFACT_ID: artifact_record(include_private=False)}
    )
    degraded = build_app(degraded_client).get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        params={"interaction_id": INTERACTION_ID},
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert invalid_service.status_code == 400
    assert invalid_service.json()["error_code"] == "ag.ae_artifact_service_invalid"
    assert missing.status_code == 404
    assert degraded.status_code == 200
    assert degraded.json()["projection_status"] == "DEGRADED"
    assert len(degraded.json()["source_status"]["errors"]) == 2


def test_artifact_operation_route_reports_primary_source_error() -> None:
    class BrokenClient(InMemoryAeArtifactOperationsClient):
        def get_artifact(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
            raise AeArtifactOperationsError(
                error_code="ag.ae_artifact_source_request_failed",
                detail="AE unavailable",
                status_code=502,
            )

    response = build_app(BrokenClient()).get(
        f"/admin/v1/operations/artifacts/{ARTIFACT_ID}",
        headers=auth_headers(),
    )

    assert response.status_code == 502
    assert response.json()["error_code"] == "ag.ae_artifact_source_request_failed"


class FakeHttpResponse:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


def test_http_artifact_operations_client_requests_expected_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> FakeHttpResponse:
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        if url.endswith(f"/api/v1/artifacts/{ARTIFACT_ID}"):
            return FakeHttpResponse(200, artifact_record(include_private=False))
        if url.endswith(f"/api/v1/artifact-handoffs/{HANDOFF_ID}"):
            return FakeHttpResponse(200, handoff_record())
        if url.endswith(f"/api/v1/chat/interactions/{INTERACTION_ID}/artifact-links"):
            return FakeHttpResponse(200, {"artifact_refs": [chat_artifact_ref()]})
        return FakeHttpResponse(404, {})

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    client = HttpAeArtifactOperationsClient(
        base_url="http://ae.example.local/",
        service_token="token-0409",
        timeout_seconds=12.5,
    )

    artifact = client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    handoff = client.get_artifact_handoff(
        HANDOFF_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    refs = client.list_chat_artifact_refs(
        INTERACTION_ID,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert artifact["artifact_id"] == ARTIFACT_ID
    assert handoff["artifact_handoff_id"] == HANDOFF_ID
    assert refs[0]["artifact_id"] == ARTIFACT_ID
    assert calls[0]["url"] == f"http://ae.example.local/api/v1/artifacts/{ARTIFACT_ID}"
    assert calls[0]["headers"]["Authorization"] == "Bearer token-0409"
    assert calls[0]["headers"]["X-Service-ID"] == "nex-ag"
    assert calls[0]["timeout"] == 12.5


def test_http_artifact_operations_client_handles_404_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        FakeHttpResponse(404, {}),
        FakeHttpResponse(404, {}),
        FakeHttpResponse(
            503,
            {
                "error_code": "ae.artifact_source_down",
                "detail": "source down",
            },
        ),
        FakeHttpResponse(500, ValueError("not json")),
        FakeHttpResponse(200, []),
    ]

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> FakeHttpResponse:
        return responses.pop(0)

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    client = HttpAeArtifactOperationsClient(base_url="http://ae.example.local")

    assert client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID) is None
    assert client.list_chat_artifact_refs(INTERACTION_ID, request_id=REQUEST_ID, trace_id=TRACE_ID) == []
    with pytest.raises(AeArtifactOperationsError) as problem:
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    with pytest.raises(AeArtifactOperationsError) as fallback:
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)
    assert client._get_json("/ok", request_id=REQUEST_ID, trace_id=TRACE_ID) == []
    assert artifact_operations._safe_response_json(FakeHttpResponse(500, [])) == {}
    assert problem.value.error_code == "ae.artifact_source_down"
    assert fallback.value.error_code == "ag.ae_artifact_source_request_failed"


def test_http_artifact_operations_client_wraps_network_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> FakeHttpResponse:
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(artifact_operations.httpx, "get", fake_get)
    client = HttpAeArtifactOperationsClient(base_url="http://ae.example.local")

    with pytest.raises(AeArtifactOperationsError) as error:
        client.get_artifact(ARTIFACT_ID, request_id=REQUEST_ID, trace_id=TRACE_ID)

    assert error.value.error_code == "ag.ae_artifact_source_unreachable"


def test_default_ae_artifact_operations_client_uses_env_and_timeout_defaults() -> None:
    defaulted = build_default_ae_artifact_operations_client({})
    configured = build_default_ae_artifact_operations_client(
        {
            NEX_AG_AE_ARTIFACT_BASE_URL_ENV: "http://ae.example.local/",
            NEX_AG_AE_ARTIFACT_SERVICE_TOKEN_ENV: "token-0409",
            NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV: "15",
        }
    )
    invalid_timeout = build_default_ae_artifact_operations_client(
        {NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV: "bad"}
    )
    negative_timeout = build_default_ae_artifact_operations_client(
        {NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS_ENV: "-1"}
    )

    assert configured.base_url == "http://ae.example.local"
    assert configured.service_token == "token-0409"
    assert configured.timeout_seconds == 15.0
    assert defaulted.timeout_seconds == DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    assert invalid_timeout.base_url == "http://127.0.0.1:8103"
    assert invalid_timeout.timeout_seconds == DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS
    assert negative_timeout.timeout_seconds == DEFAULT_AE_ARTIFACT_TIMEOUT_SECONDS


def test_artifact_operations_registered_on_main_app() -> None:
    from nex_ag.main import app

    paths = {route.path for route in app.routes}
    assert "/admin/v1/operations/artifacts/{artifact_id}" in paths
    assert AE_ARTIFACT_SOURCE_SERVICE_ID == "nex-ae-api"
