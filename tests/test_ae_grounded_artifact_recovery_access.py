from __future__ import annotations

import hashlib
from typing import Any

from fastapi.testclient import TestClient

from nex_ae_api.artifacts import (
    ArtifactRecordStore,
    build_artifact_links,
    register_artifact_handoff_routes,
)
from nex_ae_api.async_artifact_rendering import (
    admit_async_artifact_render,
    build_async_artifact_render_request,
)
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    OperationalEventError,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)

NOW = "2026-10-06T01:00:00Z"
PAYLOAD = b"# Restart-safe grounded artifact\n\nVerified answer [1].\n"


def _artifact_file() -> dict[str, Any]:
    return {
        "artifact_file_id": "artifact-file-1",
        "artifact_version_id": "artifact-version-1",
        "format": "MD",
        "mime_type": "text/markdown",
        "file_name": "grounded-report.md",
        "storage_ref": (
            "ae://artifacts/artifact-1/versions/artifact-version-1/"
            "grounded-report.md"
        ),
        "file_size_bytes": len(PAYLOAD),
        "file_hash": hashlib.sha256(PAYLOAD).hexdigest(),
        "source_version_hash": "a" * 64,
        "created_at": NOW,
    }


def _artifact() -> dict[str, Any]:
    artifact_file = _artifact_file()
    owner_ref = {
        "actor_type": "user",
        "actor_id": "owner-1",
        "tenant_id": "tenant-1",
    }
    links = build_artifact_links(
        artifact_file=artifact_file,
        created_by_actor_ref=owner_ref,
        created_at=NOW,
    )
    return {
        "artifact_id": "artifact-1",
        "artifact_status": "READY",
        "chat_document_id": "chat-document-1",
        "interaction_id": "interaction-1",
        "display_title": "Grounded report",
        "owner_actor_ref": owner_ref,
        "workspace_ref": {
            "workspace_id": "workspace-1",
            "tenant_id": "tenant-1",
        },
        "target_formats": ["MD"],
        "template_ref": {"template_id": None, "template_version": None},
        "source_refs": [
            {
                "cx_generation_id": "generation-1",
                "structured_draft_id": "draft-1",
                "structured_draft_content_hash": "b" * 64,
                "citation_claims_hash": "c" * 64,
                "quality_summary": {"citation_status": "VALIDATED"},
            }
        ],
        "versions": [],
        "render_jobs": [],
        "files": [artifact_file],
        "links": links,
        "updated_at": NOW,
    }


def _persistent_runtime() -> tuple[ArtifactRecordStore, InMemoryJobQueue, str]:
    artifact = _artifact()
    store = ArtifactRecordStore()
    store.create(artifact)
    artifact_file = artifact["files"][0]
    store.artifact_files[artifact_file["artifact_file_id"]] = artifact_file
    store.rendered_artifact_files[artifact_file["artifact_file_id"]] = PAYLOAD
    for link in artifact["links"]:
        store.artifact_links[link["artifact_link_id"]] = link
    queue = InMemoryJobQueue()
    render_request = build_async_artifact_render_request(
        artifact_record=artifact,
        render_request_id="restart-render-1",
        target_formats=["MD"],
        request_id="request-1",
        trace_id="trace-1",
        requested_at=NOW,
    )
    admit_async_artifact_render(
        request=render_request,
        artifact_store=store,
        job_queue=queue,
    )
    return store, queue, render_request["render_job_id"]


def _client(
    store: ArtifactRecordStore,
    queue: InMemoryJobQueue,
    event_store: InMemoryOperationalEventStore | None = None,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_artifact_handoff_routes(
        app,
        artifact_store=store,
        job_queue=queue,
        operational_event_store=event_store,
    )
    return TestClient(app)


def _headers(owner_user_id: str) -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id="tenant-1",
        user_id=owner_user_id,
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def _trace_headers(owner_user_id: str, request_id: str) -> dict[str, str]:
    return {
        **_headers(owner_user_id),
        "X-Request-ID": request_id,
        "traceparent": "00-13801380138013801380138013801380-00f067aa0ba902b7-01",
    }


def test_fresh_runtime_restores_owner_preview_download_and_cancelled_recovery() -> None:
    store, queue, render_job_id = _persistent_runtime()
    first_runtime = _client(store, queue)

    cancelled = first_runtime.post(
        f"/api/v1/async-artifact-render-jobs/{render_job_id}/cancel",
        headers=_headers("owner-1"),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["lifecycle_status"] == "CANCELLED"

    restarted_runtime = _client(store, queue)
    metadata = restarted_runtime.get(
        "/api/v1/artifact-files/artifact-file-1",
        headers=_headers("owner-1"),
    )
    preview = restarted_runtime.get(
        "/api/v1/artifact-files/artifact-file-1/preview",
        headers=_headers("owner-1"),
    )
    download = restarted_runtime.get(
        "/api/v1/artifact-files/artifact-file-1/download",
        headers=_headers("owner-1"),
    )
    status = restarted_runtime.get(
        f"/api/v1/async-artifact-render-jobs/{render_job_id}",
        headers=_headers("owner-1"),
    )
    recovery = restarted_runtime.get(
        f"/api/v1/async-artifact-render-jobs/{render_job_id}/recovery",
        headers=_headers("owner-1"),
    )

    assert metadata.status_code == 200
    assert "storage_ref" not in metadata.json()
    assert preview.status_code == 200
    assert preview.json()["text_preview"].startswith("# Restart-safe")
    assert "storage_ref" not in str(preview.json())
    assert download.status_code == 200
    assert download.json()["content"].startswith("# Restart-safe")
    assert "storage_ref" not in str(download.json())
    assert status.status_code == 200
    assert status.json()["lifecycle_status"] == "CANCELLED"
    assert recovery.status_code == 200
    assert recovery.json()["action"] == "NO_ACTION"


def test_artifact_file_and_recovery_routes_hide_cross_owner_state() -> None:
    store, queue, render_job_id = _persistent_runtime()
    client = _client(store, queue)
    other = _headers("other-owner")

    routes = (
        ("get", "/api/v1/artifact-files/artifact-file-1"),
        ("get", "/api/v1/artifact-files/artifact-file-1/preview"),
        ("get", "/api/v1/artifact-files/artifact-file-1/download"),
        ("get", f"/api/v1/async-artifact-render-jobs/{render_job_id}"),
        ("get", f"/api/v1/async-artifact-render-jobs/{render_job_id}/recovery"),
        ("post", f"/api/v1/async-artifact-render-jobs/{render_job_id}/cancel"),
    )
    responses = [
        getattr(client, method)(route, headers=other) for method, route in routes
    ]

    assert [response.status_code for response in responses] == [404] * len(routes)
    assert all("owner-1" not in response.text for response in responses)


def test_orphaned_file_metadata_is_not_publicly_resolvable() -> None:
    store, queue, _ = _persistent_runtime()
    orphan = {**_artifact_file(), "artifact_file_id": "orphan-file"}
    store.artifact_files["orphan-file"] = orphan
    client = _client(store, queue)

    response = client.get(
        "/api/v1/artifact-files/orphan-file",
        headers=_headers("owner-1"),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "ae.artifact_file_not_found"


def test_preview_and_denied_download_emit_traceable_access_audits() -> None:
    store, queue, _ = _persistent_runtime()
    events = InMemoryOperationalEventStore()
    client = _client(store, queue, events)

    preview = client.get(
        "/api/v1/artifact-files/artifact-file-1/preview",
        headers=_trace_headers("owner-1", "request-preview-1380"),
    )
    denied = client.get(
        "/api/v1/artifact-files/artifact-file-1/download",
        headers=_trace_headers("other-owner", "request-download-1380"),
    )
    observed = events.list_events(trace_id="13801380138013801380138013801380")

    assert preview.status_code == 200
    assert denied.status_code == 404
    assert {event["event_type"] for event in observed} == {
        "ae.artifact_access.preview.succeeded",
        "ae.artifact_access.download.blocked",
    }
    assert all(
        event["details"]["private_payload_included"] is False for event in observed
    )


class _BrokenEventStore(InMemoryOperationalEventStore):
    def append(self, event):
        del event
        raise OperationalEventError("event.store_unavailable", "unavailable", 503)


def test_artifact_access_fails_closed_when_audit_is_unavailable() -> None:
    store, queue, _ = _persistent_runtime()
    client = _client(store, queue, _BrokenEventStore())

    response = client.get(
        "/api/v1/artifact-files/artifact-file-1/preview",
        headers=_trace_headers("owner-1", "request-preview-failed-1380"),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "ae.artifact_access_audit_unavailable"
