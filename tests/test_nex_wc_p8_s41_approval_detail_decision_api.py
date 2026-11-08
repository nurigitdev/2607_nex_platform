from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from nex_runtime import issue_mock_service_token
from nex_wc.approval_api import register_approval_routes
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionError,
    ApprovalDecisionService,
    ApprovalDetailService,
    ApprovalInboxError,
    ApprovalInboxService,
    ApprovalWorkItemError,
    InMemoryApprovalWorkItemRepository,
)
from nex_wc.authorization import AuthorizationSubjectDenied

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 14, tzinfo=UTC)
WORK_ID = "41000000-0000-4000-8000-000000000001"
DECISION_ID = "41100000-0000-4000-8000-000000000001"
EVENT_ID = "41200000-0000-4000-8000-000000000001"
OUTBOX_ID = "41300000-0000-4000-8000-000000000001"


def _work_item(**overrides):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8",
        "approval_work_item_id": WORK_ID,
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-s41",
        "semantic_hash": "sha256:" + "1" * 64,
        "title": "Approve protected WRITE",
        "display_safe_summary": "Create an approved draft voucher.",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-s41",
        "target_approver_ref": "approver-s41",
        "target_role_ref": None,
        "target_org_scope_ref": "org-finance",
        "target_project_scope_ref": "project-p8",
        "agent_execution_id": "agent-execution-s41",
        "executable_step_id": "step-s41",
        "nsl_execution_id": "nsl-execution-s41",
        "business_operation_id": "operation-s41",
        "approval_request_id": "approval-request-s41",
        "protected_request_ref": "ae-private:approval-request-s41",
        "resume_target_ref": "ae-wait:approval-request-s41",
        "state": "PENDING",
        "created_at": "2026-10-22T13:00:00Z",
        "expires_at": "2026-10-23T13:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


def _request(**overrides):
    value = {
        "schema_version": "wc_approval_decision_request.v1",
        "decision": "APPROVE",
        "decision_comment": "Reviewed and approved.",
        "correlation_id": "conversation-s41",
        "causation_id": "interaction-s41",
    }
    value.update(overrides)
    return value


class AuthorizationSource:
    def __init__(self, value=None, *, error: Exception | None = None) -> None:
        self.value = value or {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s41",
            "scopes": ["approval:read", "approval:decide"],
            "roles": ["finance-approver"],
            "org_scope_refs": ["org-finance"],
            "project_scope_refs": ["project-p8"],
            "revision_hash": "1" * 64,
            "decision_ref": "oa-decision-s41",
        }
        self.error = error
        self.calls = []

    def effective_authorization(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.value


def _services(repository, source=None, *, clock=lambda: NOW):
    source = source or AuthorizationSource()
    inbox = ApprovalInboxService(
        repository, authorization_source=source, clock=clock
    )
    detail = ApprovalDetailService(
        repository, authorization_source=source, clock=clock
    )
    decision = ApprovalDecisionService(
        repository,
        authorizer=ApprovalDecisionAuthorizer(
            source, clock=lambda: NOW.replace(minute=59)
        ),
        id_factory=lambda: DECISION_ID,
        event_id_factory=lambda: EVENT_ID,
        outbox_id_factory=lambda: OUTBOX_ID,
        clock=clock,
    )
    return inbox, detail, decision, source


def test_detail_is_eligible_display_safe_and_domain_preserving() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    _, detail, _, source = _services(repository)

    result = detail.get(
        tenant_id="tenant-p8",
        subject_id="approver-s41",
        approval_work_item_id=WORK_ID,
    )

    assert source.calls == [
        {"tenant_id": "tenant-p8", "subject_id": "approver-s41"}
    ]
    assert result["gate"]["approval_domain"] == "NSL_WRITE"
    assert result["gate"]["state"] == "PENDING"
    assert result["decision_options"] == ["APPROVE", "REJECT"]
    serialized = json.dumps(result)
    for forbidden in (
        "protected_request_ref",
        "ae-private",
        "semantic_hash",
        "resume_target_ref",
        "source_ref",
    ):
        assert forbidden not in serialized


def test_detail_hides_missing_ineligible_and_expired_gates() -> None:
    for item, subject in (
        (None, "approver-s41"),
        (_work_item(target_approver_ref="other-user"), "approver-s41"),
        (_work_item(expires_at="2026-10-22T14:00:00Z"), "approver-s41"),
    ):
        repository = InMemoryApprovalWorkItemRepository()
        if item is not None:
            repository.insert(item)
        _, detail, _, _ = _services(repository)
        with pytest.raises(ApprovalInboxError) as error:
            detail.get(
                tenant_id="tenant-p8",
                subject_id=subject,
                approval_work_item_id=WORK_ID,
            )
        assert error.value.error_code == "wc.approval_gate_not_found"
        assert error.value.status_code == 404


def test_detail_validation_authorization_store_and_clock_fail_closed() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    _, detail, _, _ = _services(repository)
    for kwargs in (
        {
            "tenant_id": "bad tenant",
            "subject_id": "approver-s41",
            "approval_work_item_id": WORK_ID,
        },
        {
            "tenant_id": "tenant-p8",
            "subject_id": "bad subject",
            "approval_work_item_id": WORK_ID,
        },
        {
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s41",
            "approval_work_item_id": "not-uuid",
        },
    ):
        with pytest.raises(ApprovalInboxError) as error:
            detail.get(**kwargs)
        assert error.value.status_code == 422

    denied_source = AuthorizationSource(
        error=AuthorizationSubjectDenied("inactive")
    )
    with pytest.raises(ApprovalInboxError) as denied:
        _services(repository, denied_source)[1].get(
            tenant_id="tenant-p8",
            subject_id="approver-s41",
            approval_work_item_id=WORK_ID,
        )
    assert denied.value.status_code == 403

    class BrokenRepository:
        def get(self, **_kwargs):
            raise ApprovalWorkItemError("store", "private", 503, True)

    with pytest.raises(ApprovalInboxError) as unavailable:
        _services(BrokenRepository())[1].get(
            tenant_id="tenant-p8",
            subject_id="approver-s41",
            approval_work_item_id=WORK_ID,
        )
    assert unavailable.value.status_code == 503
    assert "private" not in unavailable.value.detail

    class ConflictRepository:
        def get(self, **_kwargs):
            raise ApprovalWorkItemError("conflict", "conflict", 409)

    with pytest.raises(ApprovalWorkItemError) as conflict:
        _services(ConflictRepository())[1].get(
            tenant_id="tenant-p8",
            subject_id="approver-s41",
            approval_work_item_id=WORK_ID,
        )
    assert conflict.value.status_code == 409

    with pytest.raises(ApprovalInboxError) as clock_error:
        _services(repository, clock=lambda: NOW.replace(tzinfo=None))[1].get(
            tenant_id="tenant-p8",
            subject_id="approver-s41",
            approval_work_item_id=WORK_ID,
        )
    assert clock_error.value.status_code == 503


@pytest.mark.parametrize(
    ("decision", "terminal_state"),
    (("APPROVE", "APPROVED"), ("REJECT", "REJECTED")),
)
def test_decision_commits_terminal_state_and_outbox_only(
    decision: str,
    terminal_state: str,
) -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    _, _, service, source = _services(repository)

    result = service.decide(
        tenant_id="tenant-p8",
        approval_work_item_id=WORK_ID,
        decision=decision,
        decided_by="approver-s41",
        decision_comment="Reviewed.",
        correlation_id="conversation-s41",
        causation_id="interaction-s41",
    )

    assert result["created"] is True
    assert result["decision"]["decision"] == decision
    assert repository.get(
        tenant_id="tenant-p8", approval_work_item_id=WORK_ID
    )["state"] == terminal_state
    events = repository.list_pending_approval_events(limit=10)
    assert len(events) == 1
    assert events[0]["event_payload"]["decision"] == decision
    assert source.calls == [
        {"tenant_id": "tenant-p8", "subject_id": "approver-s41"}
    ]


def test_exact_decision_replay_is_freshly_authorized_and_conflict_is_denied() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    _, _, service, source = _services(repository)
    arguments = {
        "tenant_id": "tenant-p8",
        "approval_work_item_id": WORK_ID,
        "decision": "APPROVE",
        "decided_by": "approver-s41",
        "decision_comment": None,
    }

    assert service.decide(**arguments)["created"] is True
    replay = service.decide(**arguments)
    assert replay["created"] is False
    assert len(source.calls) == 2
    assert len(repository.list_pending_approval_events(limit=10)) == 1

    with pytest.raises(ApprovalDecisionError) as conflict:
        service.decide(**{**arguments, "decision": "REJECT"})
    assert conflict.value.status_code == 409
    assert len(source.calls) == 3


def test_expired_invalid_and_unauthorized_decisions_leave_zero_residue() -> None:
    for source, expected_status in (
        (
            AuthorizationSource(
                value={
                    **AuthorizationSource().value,
                    "scopes": ["approval:read"],
                }
            ),
            403,
        ),
        (AuthorizationSource(error=RuntimeError("OA offline")), 503),
    ):
        repository = InMemoryApprovalWorkItemRepository()
        repository.insert(_work_item())
        service = _services(repository, source)[2]
        with pytest.raises(Exception) as error:
            service.decide(
                tenant_id="tenant-p8",
                approval_work_item_id=WORK_ID,
                decision="APPROVE",
                decided_by="approver-s41",
            )
        assert error.value.status_code == expected_status
        assert repository.get_decision(
            tenant_id="tenant-p8", approval_work_item_id=WORK_ID
        ) is None
        assert repository.list_pending_approval_events(limit=10) == []

    expired_repository = InMemoryApprovalWorkItemRepository()
    expired_repository.insert(_work_item(expires_at="2026-10-22T14:00:00Z"))
    expired_service = _services(expired_repository)[2]
    with pytest.raises(ApprovalDecisionError) as expired:
        expired_service.decide(
            tenant_id="tenant-p8",
            approval_work_item_id=WORK_ID,
            decision="APPROVE",
            decided_by="approver-s41",
        )
    assert expired.value.error_code == "wc.approval_decision_expired"
    assert expired.value.status_code == 409
    assert str(expired.value)

    for overrides in (
        {"tenant_id": "bad tenant"},
        {"approval_work_item_id": "not-uuid"},
        {"decided_by": "bad subject"},
    ):
        repository = InMemoryApprovalWorkItemRepository()
        repository.insert(_work_item())
        arguments = {
            "tenant_id": "tenant-p8",
            "approval_work_item_id": WORK_ID,
            "decision": "APPROVE",
            "decided_by": "approver-s41",
            **overrides,
        }
        with pytest.raises(ApprovalDecisionError):
            _services(repository)[2].decide(**arguments)


def _client(repository, source=None, *, include_detail=True, include_decision=True):
    inbox, detail, decision, _ = _services(repository, source)
    app = FastAPI()
    register_approval_routes(
        app,
        inbox_service=inbox,
        detail_service=detail if include_detail else None,
        decision_service=decision if include_decision else None,
    )
    return TestClient(app)


def _headers(*, token=True):
    headers = {
        "X-NeX-Tenant-Id": "tenant-p8",
        "X-NeX-Subject-Id": "approver-s41",
    }
    if token:
        issued = issue_mock_service_token(
            service_id="nex-ae-api", audience="nex-wc"
        )
        headers["Authorization"] = f"Bearer {issued.access_token}"
    return headers


def test_detail_and_decision_api_statuses_and_replay() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    client = _client(repository)

    detail = client.get(
        f"/api/v1/approval-gates/{WORK_ID}", headers=_headers()
    )
    assert detail.status_code == 200
    assert detail.json()["gate"]["state"] == "PENDING"

    created = client.post(
        f"/api/v1/approval-gates/{WORK_ID}/decisions",
        json=_request(),
        headers=_headers(),
    )
    assert created.status_code == 201
    assert created.json()["authorized_by_oa"] is True

    replay = client.post(
        f"/api/v1/approval-gates/{WORK_ID}/decisions",
        json=_request(),
        headers=_headers(),
    )
    assert replay.status_code == 200

    after = client.get(
        f"/api/v1/approval-gates/{WORK_ID}", headers=_headers()
    )
    assert after.json()["gate"]["state"] == "APPROVED"


@pytest.mark.parametrize(
    "payload",
    (
        {},
        _request(schema_version="v2"),
        _request(decision="DELETE"),
        _request(decision_comment=""),
        _request(decision_comment="x" * 2001),
        _request(correlation_id="bad id"),
        _request(causation_id=3),
    ),
)
def test_decision_api_rejects_noncanonical_requests(payload) -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    response = _client(repository).post(
        f"/api/v1/approval-gates/{WORK_ID}/decisions",
        json=payload,
        headers=_headers(),
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "wc.approval_decision_request_invalid"
    assert repository.get_decision(
        tenant_id="tenant-p8", approval_work_item_id=WORK_ID
    ) is None


def test_approval_api_requires_service_token_and_configured_dependencies() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    client = _client(repository, include_detail=False, include_decision=False)

    assert client.get(
        f"/api/v1/approval-gates/{WORK_ID}", headers=_headers(token=False)
    ).status_code == 401
    assert client.post(
        f"/api/v1/approval-gates/{WORK_ID}/decisions",
        json=_request(),
        headers=_headers(token=False),
    ).status_code == 401
    unavailable_detail = client.get(
        f"/api/v1/approval-gates/{WORK_ID}", headers=_headers()
    )
    assert unavailable_detail.status_code == 503
    unavailable_decision = client.post(
        f"/api/v1/approval-gates/{WORK_ID}/decisions",
        json=_request(),
        headers=_headers(),
    )
    assert unavailable_decision.status_code == 503


def test_detail_api_maps_ineligible_gate_to_not_found() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item(target_approver_ref="other-user"))
    response = _client(repository).get(
        f"/api/v1/approval-gates/{WORK_ID}", headers=_headers()
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "wc.approval_gate_not_found"


def test_s41_contract_examples_validate_and_negative_is_rejected() -> None:
    examples = (
        (
            "approval_gate_detail.v1.schema.json",
            "wc_approval_gate_detail.pending.json",
        ),
        (
            "approval_decision_request.v1.schema.json",
            "wc_approval_decision_request.approve.json",
        ),
    )
    for schema_name, example_name in examples:
        schema = json.loads(
            (ROOT / "contracts/schemas/service/nex_wc" / schema_name).read_text(
                encoding="utf-8"
            )
        )
        payload = json.loads(
            (ROOT / "contracts/examples/service" / example_name).read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).validate(payload)

    schema = json.loads(
        (
            ROOT
            / "contracts/schemas/service/nex_wc/approval_decision_request.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    negative = json.loads(
        (
            ROOT
            / "contracts/tests/negative/service/wc_approval_decision_request.unsupported_action.json"
        ).read_text(encoding="utf-8")
    )
    assert list(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(negative)
    )
