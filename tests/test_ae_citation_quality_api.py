from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from nex_ae_api.async_generation import build_async_generation_projection
from nex_ae_api.chat import ChatInteractionStore, register_chat_routes
from nex_ae_api.cx_async_generation_client import CxAsyncGenerationClientError
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)


class CitationHandoffClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.status = "READY"
        self.fail = False

    def get_handoff(self, job_id: str, **kwargs) -> dict:
        self.calls.append({"job_id": job_id, **kwargs})
        if self.fail:
            raise CxAsyncGenerationClientError(
                503,
                "cx.async_generation.unavailable",
                "CX handoff is unavailable.",
                True,
            )
        ready = self.status == "READY"
        return {
            "handoff_schema_version": "cx_generation_handoff.v1",
            "handoff_status": self.status,
            "next_action": (
                "PRESENT_GENERATION_TO_OWNER" if ready else "POLL_GENERATION_JOB"
            ),
            "job": {
                "job_id": "job-citation-001",
                "cx_generation_id": "cx-citation-001",
                "status": "SUCCEEDED" if ready else "RUNNING",
            },
            "generation": self._generation() if ready else None,
            "content": {"private": "not consumed"} if ready else None,
            "owner_scope_enforced": True,
        }

    def _generation(self) -> dict:
        return {
            "cx_generation_id": "cx-citation-001",
            "status": "COMPLETED",
            "request_metadata": {
                "grounding_required": True,
                "retrieval_package_id": "retrieval-001",
                "retrieval_package_hash": "a" * 64,
                "structured_draft_id": "draft-001",
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


def _async_projection() -> dict:
    return build_async_generation_projection(
        {
            "admission_status": "ENQUEUED",
            "job": {
                "job_id": "job-citation-001",
                "cx_generation_id": "cx-citation-001",
                "status": "SUCCEEDED",
                "attempt_count": 1,
                "max_attempts": 3,
                "retryable": False,
                "links": {
                    "generation": "/api/v1/generations/cx-citation-001",
                    "async_job": "/api/v1/generation-jobs/job-citation-001",
                },
                "error": None,
            },
        }
    )


def _record() -> dict:
    return {
        "interaction_id": "interaction-citation-001",
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "owner_user_id": "user-a",
        "generation": {"async_generation": _async_projection()},
    }


def _headers(tenant_id: str, user_id: str) -> dict[str, str]:
    issued = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "request-citation-api",
        "traceparent": (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        ),
    }


def _client() -> tuple[TestClient, CitationHandoffClient]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = ChatInteractionStore()
    store.save(_record())
    handoff_client = CitationHandoffClient()
    register_chat_routes(app, store=store, cx_async_client=handoff_client)
    return TestClient(app), handoff_client


def _path() -> str:
    return "/api/v1/chat/interactions/interaction-citation-001/citation-quality"


def test_owner_can_read_citation_quality_workflow() -> None:
    client, handoff_client = _client()

    response = client.get(_path(), headers=_headers("tenant-a", "user-a"))

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_status"] == "REPAIRED"
    assert body["repair"]["mode"] == "BOUNDED_INLINE"
    assert body["operator_remediation"]["mode"] == "SEPARATE_HANDOFF"
    assert "not consumed" not in str(body)
    assert handoff_client.calls[0]["tenant_id"] == "tenant-a"
    assert handoff_client.calls[0]["subject_id"] == "user-a"


def test_cross_owner_is_hidden_before_cx_handoff_lookup() -> None:
    client, handoff_client = _client()

    response = client.get(_path(), headers=_headers("tenant-a", "user-b"))

    assert response.status_code == 404
    assert response.json()["error_code"] == "ae.chat_interaction_not_found"
    assert handoff_client.calls == []


def test_citation_quality_route_requires_authentication() -> None:
    client, handoff_client = _client()

    response = client.get(_path())

    assert response.status_code == 401
    assert handoff_client.calls == []


def test_citation_quality_route_maps_not_ready_and_cx_failure() -> None:
    client, handoff_client = _client()
    handoff_client.status = "PENDING"
    pending = client.get(_path(), headers=_headers("tenant-a", "user-a"))
    handoff_client.fail = True
    failed = client.get(_path(), headers=_headers("tenant-a", "user-a"))

    assert pending.status_code == 409
    assert pending.json()["error_code"] == "ae.citation_quality_workflow.not_ready"
    assert pending.json()["retryable"] is True
    assert failed.status_code == 503
    assert failed.json()["error_code"] == "cx.async_generation.unavailable"


def test_citation_quality_route_rejects_handoff_lineage_drift() -> None:
    client, handoff_client = _client()
    original = handoff_client.get_handoff

    def drifted(*args, **kwargs):
        handoff = deepcopy(original(*args, **kwargs))
        handoff["job"]["cx_generation_id"] = "other-generation"
        return handoff

    handoff_client.get_handoff = drifted
    response = client.get(_path(), headers=_headers("tenant-a", "user-a"))

    assert response.status_code == 422
    assert response.json()["error_code"] == "ae.citation_quality_workflow.invalid"
