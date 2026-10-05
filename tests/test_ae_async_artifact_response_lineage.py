from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_ae_api.artifacts import (
    ArtifactHandoffStore,
    ArtifactRecordStore,
    register_artifact_handoff_routes,
)
from nex_ae_api.async_artifact_rendering import (
    AE_ASYNC_ARTIFACT_RESPONSE_BINDING_SCHEMA_VERSION,
    AeAsyncArtifactRenderError,
    admit_grounded_response_artifact,
    validate_async_artifact_response_lineage,
)
from nex_runtime import (
    InMemoryJobQueue,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _lineage() -> dict[str, Any]:
    return {
        "lineage_schema_version": "ae_generated_response_lineage.v1",
        "response_id": "response-1",
        "lineage_type": "ORIGINAL",
        "interaction_id": "interaction-1",
        "chat_document_id": "chat-document-1",
        "cx_generation_id": "generation-1",
        "cx_job_id": "cx-job-1",
        "content_type": "text/plain; charset=utf-8",
        "content_sha256": "c" * 64,
        "size_bytes": 24,
        "content_available": True,
        "retrieval_package_id": "retrieval-1",
        "retrieval_package_hash": "d" * 64,
        "structured_draft_id": "draft-1",
        "citation_workflow_status": "VALIDATED",
        "bounded_repair_applied": False,
        "cx_grounding_lineage": {
            "lineage_schema_version": "cx_grounded_generation_lineage.v1",
            "retrieval_package_id": "retrieval-1",
            "retrieval_package_hash": "d" * 64,
            "evidence_binding_hash": "e" * 64,
            "selected_evidence_count": 2,
            "citation_validation_status": "VALIDATED",
            "citation_repair_attempted": False,
            "citation_repair_attempt_count": 0,
            "original_provider_prompt_package_hash": "f" * 64,
            "effective_provider_prompt_package_hash": "f" * 64,
            "same_retrieval_package": True,
            "private_evidence_included": False,
        },
        "parent_interaction_id": None,
        "parent_response_id": None,
        "owner_scope_enforced": True,
        "raw_content_included": False,
        "storage_ref_included": False,
    }


def _chat_record() -> dict[str, Any]:
    return {
        "interaction_id": "interaction-1",
        "chat_document_id": "chat-document-1",
        "cx_generation_id": "generation-1",
        "workspace_id": "workspace-1",
        "tenant_id": "tenant-1",
        "user_id": "owner-1",
        "generation": {"generated_response": _lineage()},
    }


def _artifact() -> dict[str, Any]:
    return {
        "artifact_id": "artifact-1",
        "artifact_status": "DRAFT",
        "chat_document_id": "chat-document-1",
        "interaction_id": "interaction-1",
        "display_title": "Grounded report",
        "owner_actor_ref": {
            "actor_type": "user",
            "actor_id": "owner-1",
            "tenant_id": "tenant-1",
        },
        "workspace_ref": {
            "workspace_id": "workspace-1",
            "tenant_id": "tenant-1",
        },
        "target_formats": ["MD", "PDF"],
        "template_ref": {"template_id": "template-1", "template_version": "1"},
        "source_refs": [
            {
                "cx_generation_id": "generation-1",
                "structured_draft_id": "draft-1",
                "structured_draft_content_hash": DIGEST_A,
                "citation_claims_hash": DIGEST_B,
                "retrieval_package_id": "retrieval-1",
                "retrieval_package_hash": "d" * 64,
                "evidence_ref_count": 2,
                "source_anchor_count": 2,
                "quality_summary": {
                    "citation_status": "VALIDATED",
                    "grounding_required": True,
                },
            }
        ],
        "versions": [],
        "render_jobs": [],
        "files": [],
        "links": [],
        "updated_at": "2026-09-29T05:00:00Z",
    }


@dataclass
class StubLineageStore:
    record: dict[str, Any] | None
    error: Exception | None = None
    calls: list[dict[str, str]] | None = None

    def get_for_owner(
        self,
        interaction_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> dict[str, Any] | None:
        if self.calls is None:
            self.calls = []
        self.calls.append(
            {
                "interaction_id": interaction_id,
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
            }
        )
        if self.error is not None:
            raise self.error
        if self.record is None:
            return None
        if (
            self.record.get("tenant_id") != tenant_id
            or self.record.get("user_id") != owner_user_id
        ):
            return None
        return deepcopy(self.record)


def test_response_lineage_binding_is_owner_scoped_and_content_free() -> None:
    store = StubLineageStore(_chat_record())

    result = validate_async_artifact_response_lineage(
        artifact_record=_artifact(),
        response_id="response-1",
        lineage_store=store,
    )

    assert result == {
        "response_binding_schema_version": (
            AE_ASYNC_ARTIFACT_RESPONSE_BINDING_SCHEMA_VERSION
        ),
        "response_id": "response-1",
        "interaction_id": "interaction-1",
        "chat_document_id": "chat-document-1",
        "cx_generation_id": "generation-1",
        "structured_draft_id": "draft-1",
        "lineage_type": "ORIGINAL",
        "citation_workflow_status": "VALIDATED",
        "owner_scope_enforced": True,
        "content_included": False,
    }
    assert store.calls == [
        {
            "interaction_id": "interaction-1",
            "tenant_id": "tenant-1",
            "owner_user_id": "owner-1",
        }
    ]
    assert "content_sha256" not in result


@pytest.mark.parametrize(
    ("record_mutation", "response_id"),
    [
        (lambda record: None, "other-response"),
        (lambda record: record.update(workspace_id="other-workspace"), "response-1"),
        (
            lambda record: (
                record.update(chat_document_id="other-document"),
                record["generation"]["generated_response"].update(
                    chat_document_id="other-document"
                ),
            ),
            "response-1",
        ),
        (
            lambda record: (
                record.update(cx_generation_id="other-generation"),
                record["generation"]["generated_response"].update(
                    cx_generation_id="other-generation"
                ),
            ),
            "response-1",
        ),
        (
            lambda record: record["generation"]["generated_response"].update(
                structured_draft_id="other-draft"
            ),
            "response-1",
        ),
    ],
)
def test_response_lineage_binding_rejects_cross_lineage_references(
    record_mutation,
    response_id: str,
) -> None:
    record = _chat_record()
    record_mutation(record)

    with pytest.raises(AeAsyncArtifactRenderError) as exc_info:
        validate_async_artifact_response_lineage(
            artifact_record=_artifact(),
            response_id=response_id,
            lineage_store=StubLineageStore(record),
        )

    assert exc_info.value.error_code.endswith("response_lineage_mismatch")
    assert exc_info.value.status_code == 409


def test_response_lineage_binding_hides_missing_and_cross_owner_records() -> None:
    for store in (
        StubLineageStore(None),
        StubLineageStore({**_chat_record(), "user_id": "other-owner"}),
    ):
        with pytest.raises(AeAsyncArtifactRenderError) as exc_info:
            validate_async_artifact_response_lineage(
                artifact_record=_artifact(),
                response_id="response-1",
                lineage_store=store,
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.error_code.endswith("response_not_found")


def test_response_lineage_binding_reports_pending_invalid_and_unavailable_state() -> None:
    pending = _chat_record()
    pending["generation"] = {}
    invalid = _chat_record()
    invalid["generation"]["generated_response"]["content_available"] = False

    with pytest.raises(AeAsyncArtifactRenderError) as pending_error:
        validate_async_artifact_response_lineage(
            artifact_record=_artifact(),
            response_id="response-1",
            lineage_store=StubLineageStore(pending),
        )
    with pytest.raises(AeAsyncArtifactRenderError) as invalid_error:
        validate_async_artifact_response_lineage(
            artifact_record=_artifact(),
            response_id="response-1",
            lineage_store=StubLineageStore(invalid),
        )
    with pytest.raises(AeAsyncArtifactRenderError) as unavailable_error:
        validate_async_artifact_response_lineage(
            artifact_record=_artifact(),
            response_id="response-1",
            lineage_store=StubLineageStore(
                _chat_record(), error=RuntimeError("database unavailable")
            ),
        )

    assert pending_error.value.error_code.endswith("response_not_ready")
    assert pending_error.value.retryable is True
    assert invalid_error.value.error_code.endswith("response_lineage_invalid")
    assert invalid_error.value.status_code == 503
    assert unavailable_error.value.error_code.endswith("response_lineage_unavailable")
    assert unavailable_error.value.retryable is True


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda lineage: lineage.update(cx_grounding_lineage=None),
            "grounding_lineage_required",
        ),
        (
            lambda lineage: lineage["cx_grounding_lineage"].update(
                retrieval_package_hash="9" * 64
            ),
            "response_lineage_invalid",
        ),
        (
            lambda lineage: lineage["cx_grounding_lineage"].update(
                selected_evidence_count=3
            ),
            "grounding_lineage_mismatch",
        ),
    ],
)
def test_grounded_response_binding_rejects_missing_or_drifted_grounding_lineage(
    mutation,
    expected_code: str,
) -> None:
    record = _chat_record()
    mutation(record["generation"]["generated_response"])

    with pytest.raises(AeAsyncArtifactRenderError) as exc_info:
        validate_async_artifact_response_lineage(
            artifact_record=_artifact(),
            response_id="response-1",
            lineage_store=StubLineageStore(record),
        )

    assert exc_info.value.error_code.endswith(expected_code)


def test_grounded_response_admission_creates_artifact_and_content_free_job() -> None:
    artifact_store = ArtifactRecordStore()
    queue = InMemoryJobQueue()

    result = admit_grounded_response_artifact(
        artifact_record=_artifact(),
        response_id="response-1",
        lineage_store=StubLineageStore(_chat_record()),
        artifact_store=artifact_store,
        job_queue=queue,
        render_request_id="render-request-1",
        target_formats=["MD"],
        request_id="request-1",
        trace_id="trace-1",
        requested_at="2026-10-06T00:00:00Z",
    )

    job_id = result["render_admission"]["render"]["render_job_id"]
    queued = queue.get_job(job_id)
    assert result["artifact"]["artifact_status"] == "RENDERING"
    assert result["response_binding"]["response_id"] == "response-1"
    assert result["content_included"] is False
    assert queued["payload"]["render_request"]["response_id"] == "response-1"
    assert queued["payload"]["render_request"]["content_included"] is False
    assert "content_sha256" not in str(queued)


def _user_headers() -> dict[str, str]:
    token = issue_mock_user_token(tenant_id="tenant-1", user_id="owner-1")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "Idempotency-Key": "render-request-1",
    }


def _route_client(
    lineage_store: StubLineageStore | None,
) -> tuple[TestClient, InMemoryJobQueue]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    artifact_store = ArtifactRecordStore()
    artifact_store.create(_artifact())
    queue = InMemoryJobQueue()
    register_artifact_handoff_routes(
        app,
        artifact_store=artifact_store,
        job_queue=queue,
    )
    if lineage_store is not None:
        app.state.ae_chat_store = lineage_store
    return TestClient(app), queue


def _handoff() -> dict[str, Any]:
    return {
        "handoff_schema_version": "ae_artifact_handoff.v1",
        "artifact_handoff_id": "handoff-1",
        "artifact_request_id": "artifact-request-1",
        "handoff_status": "READY_FOR_RENDERING",
        "trace_id": "1" * 32,
        "request_id": "request-1",
        "chat_document_id": "chat-document-1",
        "interaction_id": "interaction-1",
        "actor_claims_ref": {
            "actor_type": "user",
            "actor_id": "owner-1",
            "tenant_id": "tenant-1",
        },
        "workspace_ref": {
            "workspace_id": "workspace-1",
            "tenant_id": "tenant-1",
        },
        "cx_generation_id": "generation-1",
        "structured_draft_id": "draft-1",
        "draft_schema_version": "cx_structured_draft.v1",
        "structured_draft_content_hash": DIGEST_A,
        "citation_claims_hash": DIGEST_B,
        "validation_result_hash": "3" * 64,
        "template_id": None,
        "template_version": None,
        "rendering_template_id": None,
        "artifact_intent": "create_artifact",
        "target_formats": ["MD"],
        "artifact_title": "Grounded report",
        "language": "ko",
        "retention_policy_ref": "retention-1",
        "quality_summary": {
            "citation_status": "VALIDATED",
            "citation_count": 2,
            "validation_error_count": 0,
            "warning_count": 0,
            "grounding_required": True,
            "retrieval_package_id": "retrieval-1",
            "retrieval_package_hash": "d" * 64,
            "evidence_ref_count": 2,
        },
        "created_at": "2026-10-06T00:00:00Z",
        "updated_at": "2026-10-06T00:00:00Z",
    }


def _grounded_route_client() -> tuple[TestClient, InMemoryJobQueue]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    handoff_store = ArtifactHandoffStore()
    handoff_store.save(_handoff())
    queue = InMemoryJobQueue()
    app.state.ae_chat_store = StubLineageStore(_chat_record())
    register_artifact_handoff_routes(
        app,
        store=handoff_store,
        artifact_store=ArtifactRecordStore(),
        job_queue=queue,
    )
    return TestClient(app), queue


def test_grounded_response_artifact_route_is_owner_scoped_and_idempotent() -> None:
    client, queue = _grounded_route_client()
    payload = {"artifact_handoff_id": "handoff-1", "target_formats": ["MD"]}

    admitted = client.post(
        "/api/v1/generated-responses/response-1/artifacts",
        json=payload,
        headers=_user_headers(),
    )
    repeated = client.post(
        "/api/v1/generated-responses/response-1/artifacts",
        json=payload,
        headers=_user_headers(),
    )
    other_token = issue_mock_user_token(tenant_id="tenant-1", user_id="other-owner")
    hidden = client.post(
        "/api/v1/generated-responses/response-1/artifacts",
        json=payload,
        headers={
            "Authorization": f"Bearer {other_token.access_token}",
            "Idempotency-Key": "render-request-1",
        },
    )

    assert admitted.status_code == 202
    assert admitted.json()["artifact"]["artifact_status"] == "RENDERING"
    assert admitted.json()["render_admission"]["admission_status"] == "ENQUEUED"
    assert repeated.status_code == 202
    assert repeated.json()["render_admission"]["admission_status"] == "JOINED"
    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "ae.grounded_artifact.handoff_not_found"
    assert len(queue.list_jobs()) == 1


def test_async_render_route_admits_only_matching_generated_response() -> None:
    client, queue = _route_client(StubLineageStore(_chat_record()))

    response = client.post(
        "/api/v1/artifacts/artifact-1/async-render-jobs",
        json={"target_formats": ["MD"], "response_id": "response-1"},
        headers=_user_headers(),
    )

    assert response.status_code == 202
    job_id = response.json()["render"]["render_job_id"]
    queued_request = queue.get_job(job_id)["payload"]["render_request"]
    assert queued_request["response_id"] == "response-1"
    assert queued_request["content_included"] is False


def test_async_render_route_fails_closed_for_missing_or_mismatched_lineage() -> None:
    unavailable_client, _ = _route_client(None)
    mismatch_client, _ = _route_client(StubLineageStore(_chat_record()))

    unavailable = unavailable_client.post(
        "/api/v1/artifacts/artifact-1/async-render-jobs",
        json={"target_formats": ["MD"], "response_id": "response-1"},
        headers=_user_headers(),
    )
    mismatch = mismatch_client.post(
        "/api/v1/artifacts/artifact-1/async-render-jobs",
        json={"target_formats": ["MD"], "response_id": "other-response"},
        headers=_user_headers(),
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True
    assert mismatch.status_code == 409
    assert mismatch.json()["error_code"].endswith("response_lineage_mismatch")
