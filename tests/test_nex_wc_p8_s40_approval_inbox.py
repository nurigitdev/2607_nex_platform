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
    APPROVAL_INBOX_SCAN_LIMIT,
    ApprovalInboxError,
    ApprovalInboxService,
    ApprovalWorkItemError,
    InMemoryApprovalWorkItemRepository,
    SqlAlchemyApprovalWorkItemRepository,
)
from nex_wc.authorization import AuthorizationSubjectDenied
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
WORK_ID = "40000000-0000-4000-8000-000000000001"


def _work_item(**overrides):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8",
        "approval_work_item_id": WORK_ID,
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-s40-001",
        "semantic_hash": "sha256:" + "4" * 64,
        "title": "Approve protected WRITE",
        "display_safe_summary": "Create an approved draft voucher.",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-s40-001",
        "target_approver_ref": "approver-s40",
        "target_role_ref": None,
        "target_org_scope_ref": "org-finance",
        "target_project_scope_ref": "project-p8",
        "agent_execution_id": "agent-execution-s40",
        "executable_step_id": "step-s40",
        "nsl_execution_id": "nsl-execution-s40",
        "business_operation_id": "operation-s40",
        "approval_request_id": "approval-request-s40-001",
        "protected_request_ref": "ae-private:approval-request-s40-001",
        "resume_target_ref": "ae-wait:approval-request-s40-001",
        "state": "PENDING",
        "created_at": "2026-10-22T11:00:00Z",
        "expires_at": "2026-10-23T11:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


class AuthorizationSource:
    def __init__(self, value=None, *, error: Exception | None = None) -> None:
        self.value = value or {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s40",
            "scopes": ["approval:read"],
            "roles": ["finance-approver"],
            "org_scope_refs": ["org-finance"],
            "project_scope_refs": ["project-p8"],
            "revision_hash": "4" * 64,
        }
        self.error = error
        self.calls = []

    def effective_authorization(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.value


def _service(repository, source=None, *, clock=lambda: NOW):
    return ApprovalInboxService(
        repository,
        authorization_source=source or AuthorizationSource(),
        clock=clock,
    )


def test_inbox_returns_only_current_eligible_safe_pending_gates() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    repository.insert(
        _work_item(
            approval_work_item_id="40000000-0000-4000-8000-000000000002",
            source_ref="approval-request-s40-002",
            approval_target_ref="approval-request-s40-002",
            approval_request_id="approval-request-s40-002",
            protected_request_ref="ae-private:approval-request-s40-002",
            target_approver_ref="other-user",
        )
    )
    repository.insert(
        _work_item(
            approval_work_item_id="40000000-0000-4000-8000-000000000003",
            source_ref="approval-request-s40-003",
            approval_target_ref="approval-request-s40-003",
            approval_request_id="approval-request-s40-003",
            protected_request_ref="ae-private:approval-request-s40-003",
            target_approver_ref=None,
            target_role_ref="finance-approver",
        )
    )
    repository.insert(
        _work_item(
            approval_work_item_id="40000000-0000-4000-8000-000000000004",
            source_ref="approval-request-s40-004",
            approval_target_ref="approval-request-s40-004",
            approval_request_id="approval-request-s40-004",
            protected_request_ref="ae-private:approval-request-s40-004",
            expires_at="2026-10-22T12:00:00Z",
        )
    )
    repository.insert(
        _work_item(
            approval_work_item_id="40000000-0000-4000-8000-000000000005",
            source_ref="approval-request-s40-005",
            approval_target_ref="approval-request-s40-005",
            approval_request_id="approval-request-s40-005",
            protected_request_ref="ae-private:approval-request-s40-005",
            state="APPROVED",
        )
    )

    result = _service(repository).list_pending(
        tenant_id="tenant-p8", subject_id="approver-s40"
    )

    assert [gate["gate_id"] for gate in result["gates"]] == [
        WORK_ID,
        "40000000-0000-4000-8000-000000000003",
    ]
    assert result["returned_count"] == 2
    assert result["scan_truncated"] is False
    serialized = json.dumps(result)
    for forbidden in (
        "protected_request_ref",
        "ae-private",
        "semantic_hash",
        "resume_target_ref",
        "source_ref",
    ):
        assert forbidden not in serialized
    assert result["gates"][0]["approval_domain"] == "NSL_WRITE"
    assert result["gates"][0]["approval_provider_type"] == "NSL"


def test_inbox_is_tenant_scoped_ordered_and_limited() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(
        _work_item(
            approval_work_item_id="40000000-0000-4000-8000-000000000002",
            source_ref="approval-request-s40-002",
            approval_target_ref="approval-request-s40-002",
            approval_request_id="approval-request-s40-002",
            created_at="2026-10-22T11:01:00Z",
        )
    )
    repository.insert(_work_item())
    repository.insert(
        _work_item(
            tenant_id="tenant-other",
            approval_work_item_id="40000000-0000-4000-8000-000000000003",
            source_ref="approval-request-s40-003",
            approval_target_ref="approval-request-s40-003",
            approval_request_id="approval-request-s40-003",
        )
    )

    result = _service(repository).list_pending(
        tenant_id="tenant-p8", subject_id="approver-s40", limit=1
    )
    assert result["returned_count"] == 1
    assert result["gates"][0]["gate_id"] == WORK_ID
    assert repository.list_pending_work_items(
        tenant_id="tenant-other", limit=10
    )[0]["tenant_id"] == "tenant-other"


@pytest.mark.parametrize(
    "authorization",
    (
        {
            "active": False,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s40",
            "scopes": ["approval:read"],
            "revision_hash": "4" * 64,
        },
        {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s40",
            "scopes": [],
            "revision_hash": "4" * 64,
        },
        {
            "active": True,
            "tenant_id": "tenant-other",
            "subject_id": "approver-s40",
            "scopes": ["approval:read"],
            "revision_hash": "4" * 64,
        },
        {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "other-user",
            "scopes": ["approval:read"],
            "revision_hash": "4" * 64,
        },
    ),
)
def test_inbox_requires_current_read_authority(authorization) -> None:
    source = AuthorizationSource(authorization)
    with pytest.raises(ApprovalInboxError) as error:
        _service(InMemoryApprovalWorkItemRepository(), source).list_pending(
            tenant_id="tenant-p8", subject_id="approver-s40"
        )
    assert error.value.status_code == 403
    assert error.value.retryable is False


def test_inbox_distinguishes_typed_denial_and_dependency_failure() -> None:
    for source, status, retryable in (
        (
            AuthorizationSource(error=AuthorizationSubjectDenied("inactive")),
            403,
            False,
        ),
        (AuthorizationSource(error=RuntimeError("OA offline")), 503, True),
    ):
        with pytest.raises(ApprovalInboxError) as error:
            _service(InMemoryApprovalWorkItemRepository(), source).list_pending(
                tenant_id="tenant-p8", subject_id="approver-s40"
            )
        assert error.value.status_code == status
        assert error.value.retryable is retryable
        assert "offline" not in error.value.detail


@pytest.mark.parametrize(
    ("tenant_id", "subject_id", "limit"),
    (
        ("bad tenant", "approver-s40", 50),
        ("tenant-p8", "bad subject", 50),
        ("tenant-p8", "approver-s40", 0),
        ("tenant-p8", "approver-s40", 101),
        ("tenant-p8", "approver-s40", True),
    ),
)
def test_inbox_input_is_bounded_and_validated(tenant_id, subject_id, limit) -> None:
    with pytest.raises(ApprovalInboxError) as error:
        _service(InMemoryApprovalWorkItemRepository()).list_pending(
            tenant_id=tenant_id,
            subject_id=subject_id,
            limit=limit,
        )
    assert error.value.status_code == 422


def test_inbox_store_failure_clock_and_scan_truncation() -> None:
    class Repository:
        def __init__(self, error=None, rows=()):
            self.error = error
            self.rows = rows

        def list_pending_work_items(self, **_kwargs):
            if self.error:
                raise self.error
            return self.rows

    unavailable = ApprovalWorkItemError("store", "private", 503, True)
    with pytest.raises(ApprovalInboxError) as store_error:
        _service(Repository(unavailable)).list_pending(
            tenant_id="tenant-p8", subject_id="approver-s40"
        )
    assert store_error.value.status_code == 503
    assert "private" not in store_error.value.detail

    conflict = ApprovalWorkItemError("conflict", "conflict", 409)
    with pytest.raises(ApprovalWorkItemError) as propagated:
        _service(Repository(conflict)).list_pending(
            tenant_id="tenant-p8", subject_id="approver-s40"
        )
    assert propagated.value is conflict

    with pytest.raises(ApprovalInboxError) as clock_error:
        _service(
            InMemoryApprovalWorkItemRepository(),
            clock=lambda: NOW.replace(tzinfo=None),
        ).list_pending(tenant_id="tenant-p8", subject_id="approver-s40")
    assert clock_error.value.status_code == 503

    repeated = [_work_item()] * APPROVAL_INBOX_SCAN_LIMIT
    truncated = _service(Repository(rows=repeated)).list_pending(
        tenant_id="tenant-p8", subject_id="approver-s40", limit=1
    )
    assert truncated["scan_truncated"] is True


def _sql_factory(*, with_schema=True):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    if with_schema:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE wc_approval_work_item (
                    tenant_id TEXT NOT NULL,
                    approval_work_item_id TEXT NOT NULL,
                    approval_domain TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    title TEXT NOT NULL,
                    display_safe_summary TEXT NOT NULL,
                    approval_provider_type TEXT NOT NULL,
                    approval_target_ref TEXT NOT NULL,
                    target_approver_ref TEXT NULL,
                    target_role_ref TEXT NULL,
                    target_org_scope_ref TEXT NULL,
                    target_project_scope_ref TEXT NULL,
                    agent_execution_id TEXT NULL,
                    executable_step_id TEXT NULL,
                    nsl_execution_id TEXT NULL,
                    business_operation_id TEXT NULL,
                    approval_request_id TEXT NULL,
                    protected_request_ref TEXT NULL,
                    resume_target_ref TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NULL,
                    version INTEGER NOT NULL,
                    PRIMARY KEY (tenant_id, approval_work_item_id),
                    UNIQUE (tenant_id, approval_domain, source_ref)
                )
            """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine


def test_sql_repository_lists_pending_after_restart_and_maps_failure() -> None:
    factory, engine = _sql_factory()
    try:
        repository = SqlAlchemyApprovalWorkItemRepository(factory)
        repository.insert(_work_item())
        repository.insert(
            _work_item(
                approval_work_item_id="40000000-0000-4000-8000-000000000002",
                source_ref="approval-request-s40-002",
                approval_target_ref="approval-request-s40-002",
                approval_request_id="approval-request-s40-002",
                state="REJECTED",
            )
        )
        restarted = SqlAlchemyApprovalWorkItemRepository(factory)
        rows = restarted.list_pending_work_items(tenant_id="tenant-p8", limit=10)
        assert [row["approval_work_item_id"] for row in rows] == [WORK_ID]
        assert restarted.list_pending_work_items(
            tenant_id="tenant-other", limit=10
        ) == []
    finally:
        engine.dispose()

    missing_factory, missing_engine = _sql_factory(with_schema=False)
    try:
        with pytest.raises(ApprovalWorkItemError) as unavailable:
            SqlAlchemyApprovalWorkItemRepository(
                missing_factory
            ).list_pending_work_items(tenant_id="tenant-p8", limit=10)
        assert unavailable.value.status_code == 503
    finally:
        missing_engine.dispose()


def _client(service):
    app = FastAPI()
    register_approval_routes(app, inbox_service=service)
    return TestClient(app)


def _headers(*, token=True):
    headers = {
        "X-NeX-Tenant-Id": "tenant-p8",
        "X-NeX-Subject-Id": "approver-s40",
    }
    if token:
        issued = issue_mock_service_token(
            service_id="nex-ae-api", audience="nex-wc"
        )
        headers["Authorization"] = f"Bearer {issued.access_token}"
    return headers


def test_protected_approval_inbox_api_and_problem_mapping() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    client = _client(_service(repository))
    assert client.get("/api/v1/approval-gates", headers=_headers(token=False)).status_code == 401

    response = client.get(
        "/api/v1/approval-gates?limit=10", headers=_headers()
    )
    assert response.status_code == 200
    assert response.json()["returned_count"] == 1

    denied_client = _client(
        _service(
            repository,
            AuthorizationSource(error=AuthorizationSubjectDenied("inactive")),
        )
    )
    denied = denied_client.get("/api/v1/approval-gates", headers=_headers())
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "wc.approval_inbox_authorization_denied"


def test_inbox_contract_positive_and_negative_examples() -> None:
    schema = json.loads(
        (
            ROOT / "contracts/schemas/service/nex_wc/approval_inbox.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    positive = json.loads(
        (
            ROOT / "contracts/examples/service/wc_approval_inbox.pending.json"
        ).read_text(encoding="utf-8")
    )
    validator.validate(positive)
    negative = json.loads(
        (
            ROOT
            / "contracts/tests/negative/service/wc_approval_inbox.raw_protected_payload.json"
        ).read_text(encoding="utf-8")
    )
    assert list(validator.iter_errors(negative))
