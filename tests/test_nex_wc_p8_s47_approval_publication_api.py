from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_runtime import issue_mock_service_token
from nex_wc.approval_api import register_approval_routes
from nex_wc.approvals import (
    ApprovalInboxService,
    ApprovalWorkItemService,
    InMemoryApprovalWorkItemRepository,
)

WORK_ID = "47000000-0000-4000-8000-000000000001"


class AuthorizationSource:
    def effective_authorization(self, **kwargs):
        return {
            "active": True,
            "tenant_id": kwargs["tenant_id"],
            "subject_id": kwargs["subject_id"],
            "scopes": ["approval:read"],
            "roles": [],
            "org_scope_refs": [],
            "project_scope_refs": [],
            "revision_hash": "a" * 64,
            "decision_ref": "oa-decision-p8-s47",
        }


def _work_item(**changes):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8-s47",
        "approval_work_item_id": WORK_ID,
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-p8-s47",
        "semantic_hash": "sha256:" + "a" * 64,
        "title": "Approve NSL WRITE",
        "display_safe_summary": "{\"amount\":\"12000\"}",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-p8-s47",
        "target_approver_ref": "approver-p8-s47",
        "target_role_ref": None,
        "target_org_scope_ref": None,
        "target_project_scope_ref": None,
        "agent_execution_id": "agent-execution-p8-s47",
        "executable_step_id": "step-p8-s47",
        "nsl_execution_id": "nsl-execution-p8-s47",
        "business_operation_id": "business-operation-p8-s47",
        "approval_request_id": "approval-request-p8-s47",
        "protected_request_ref": (
            "ae://nsl-approval-requests/aa/" + "b" * 64 + ".json"
        ),
        "resume_target_ref": "ae-wait:wait-p8-s47",
        "state": "PENDING",
        "created_at": "2026-10-22T12:00:00Z",
        "expires_at": "2026-10-23T12:00:00Z",
        "version": 1,
    }
    value.update(changes)
    return value


def _client(*, include_service: bool = True) -> TestClient:
    repository = InMemoryApprovalWorkItemRepository()
    app = FastAPI()
    register_approval_routes(
        app,
        inbox_service=ApprovalInboxService(
            repository, authorization_source=AuthorizationSource()
        ),
        work_item_service=(
            ApprovalWorkItemService(repository) if include_service else None
        ),
    )
    return TestClient(app)


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-wc"
    ).access_token
    return {"Authorization": f"Bearer {token}"}


def test_service_route_creates_and_replays_uri_backed_approval_work_item() -> None:
    client = _client()

    created = client.post(
        "/api/v1/approval-work-items", json=_work_item(), headers=_headers()
    )
    replay = client.post(
        "/api/v1/approval-work-items", json=_work_item(), headers=_headers()
    )

    assert created.status_code == 201
    assert created.json()["created"] is True
    assert replay.status_code == 200
    assert replay.json()["created"] is False
    assert replay.json()["work_item"]["protected_request_ref"].startswith("ae://")


def test_service_route_requires_token_dependency_and_immutable_semantics() -> None:
    assert _client().post(
        "/api/v1/approval-work-items", json=_work_item()
    ).status_code == 401
    assert _client(include_service=False).post(
        "/api/v1/approval-work-items", json=_work_item(), headers=_headers()
    ).status_code == 503

    client = _client()
    assert client.post(
        "/api/v1/approval-work-items", json=_work_item(), headers=_headers()
    ).status_code == 201
    conflict = client.post(
        "/api/v1/approval-work-items",
        json=_work_item(semantic_hash="sha256:" + "c" * 64),
        headers=_headers(),
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"].endswith("idempotency_conflict")
