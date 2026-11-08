from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionError,
    ApprovalDecisionService,
    InMemoryApprovalWorkItemRepository,
    SqlAlchemyApprovalWorkItemRepository,
    validate_approval_decision,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

WORK_ID = "37000000-0000-4000-8000-000000000001"
DECISION_ID = "37100000-0000-4000-8000-000000000001"


def _work_item(**overrides):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8",
        "approval_work_item_id": WORK_ID,
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-s37",
        "semantic_hash": "sha256:" + "7" * 64,
        "title": "Approve protected WRITE",
        "display_safe_summary": "Create the approved voucher draft.",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-s37",
        "target_approver_ref": "approver-s37",
        "target_role_ref": None,
        "target_org_scope_ref": "org-finance",
        "target_project_scope_ref": "project-p8",
        "agent_execution_id": "agent-execution-s37",
        "executable_step_id": "step-s37",
        "nsl_execution_id": "nsl-execution-s37",
        "business_operation_id": "operation-s37",
        "approval_request_id": "approval-request-s37",
        "protected_request_ref": "ae-private:approval-request-s37",
        "resume_target_ref": "ae-wait:approval-request-s37",
        "state": "PENDING",
        "created_at": "2026-10-22T12:00:00Z",
        "expires_at": "2026-10-23T12:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


def _decision(**overrides):
    value = {
        "schema_version": "wc_approval_decision.v1",
        "tenant_id": "tenant-p8",
        "decision_id": DECISION_ID,
        "approval_work_item_id": WORK_ID,
        "decision": "APPROVE",
        "decided_by": "approver-s37",
        "decision_comment": "Approved.",
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-decision-s37",
        "authorization_revision_hash": "sha256:" + "a" * 64,
        "authorization_checked_at": "2026-10-22T12:29:59Z",
        "decided_at": "2026-10-22T12:30:00Z",
    }
    value.update(overrides)
    return value


def _outbox(decision=None):
    decision = decision or _decision()
    event = {
        "schema_version": "wc_approval_event.v1",
        "tenant_id": decision["tenant_id"],
        "event_id": "37200000-0000-4000-8000-000000000001",
        "event_type": "NSL_APPROVAL_DECIDED",
        "approval_work_item_id": decision["approval_work_item_id"],
        "decision_id": decision["decision_id"],
        "approval_domain": "NSL_WRITE",
        "decision": decision["decision"],
        "decided_by": decision["decided_by"],
        "oa_decision_ref": decision["oa_decision_ref"],
        "occurred_at": decision["decided_at"],
        "correlation_id": decision["approval_work_item_id"],
        "causation_id": decision["approval_work_item_id"],
    }
    return {
        "tenant_id": decision["tenant_id"],
        "outbox_id": "37300000-0000-4000-8000-000000000001",
        "event_id": event["event_id"],
        "approval_work_item_id": decision["approval_work_item_id"],
        "decision_id": decision["decision_id"],
        "event_type": event["event_type"],
        "event_payload": event,
        "delivery_state": "PENDING",
        "enqueued_job_id": None,
        "created_at": decision["decided_at"],
        "updated_at": decision["decided_at"],
    }


class _AuthorizationSource:
    def __init__(self):
        self.calls = []

    def effective_authorization(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s37",
            "scopes": ["approval:decide"],
            "roles": [],
            "revision_hash": "a" * 64,
            "decision_ref": "oa-decision-s37",
        }


def _service(repository, source=None):
    source = source or _AuthorizationSource()
    ids = iter(
        (
            DECISION_ID,
            "37100000-0000-4000-8000-000000000002",
            "37100000-0000-4000-8000-000000000003",
        )
    )
    return (
        ApprovalDecisionService(
            repository,
            authorizer=ApprovalDecisionAuthorizer(
                source,
                clock=lambda: datetime(2026, 10, 22, 12, 29, 59, tzinfo=UTC),
            ),
            id_factory=lambda: next(ids),
            clock=lambda: datetime(2026, 10, 22, 12, 30, tzinfo=UTC),
        ),
        source,
    )


def _factory(*, with_schema=True):
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
            connection.execute(text("""
                CREATE TABLE wc_approval_decision (
                    tenant_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    approval_work_item_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    decided_by TEXT NOT NULL,
                    decision_comment TEXT NULL,
                    decision_version INTEGER NOT NULL,
                    authorized_by_oa BOOLEAN NOT NULL,
                    oa_decision_ref TEXT NOT NULL,
                    authorization_revision_hash TEXT NOT NULL,
                    authorization_checked_at TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, decision_id),
                    UNIQUE (tenant_id, approval_work_item_id, decision_version)
                )
            """))
            connection.execute(text("""
                CREATE TABLE wc_approval_outbox (
                    tenant_id TEXT NOT NULL,
                    outbox_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    approval_work_item_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_payload TEXT NOT NULL,
                    delivery_state TEXT NOT NULL,
                    enqueued_job_id TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, outbox_id),
                    UNIQUE (tenant_id, event_id)
                )
            """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine


@pytest.mark.parametrize(
    "repository_factory",
    (InMemoryApprovalWorkItemRepository,),
)
def test_s37_approve_commits_one_immutable_decision_and_terminal_projection(
    repository_factory,
):
    repository = repository_factory()
    repository.insert(_work_item())
    service, source = _service(repository)

    result = service.decide(
        tenant_id="tenant-p8",
        approval_work_item_id=WORK_ID,
        decision="approve",
        decided_by="approver-s37",
        decision_comment="Approved.",
    )
    assert result["created"] is True
    assert result["decision"] == _decision()
    assert repository.get_decision(
        tenant_id="tenant-p8", approval_work_item_id=WORK_ID
    ) == _decision()
    item = repository.get(tenant_id="tenant-p8", approval_work_item_id=WORK_ID)
    assert item["state"] == "APPROVED"
    assert item["version"] == 2
    assert len(source.calls) == 1


def test_s37_exact_replay_reauthorizes_and_returns_original_decision():
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    service, source = _service(repository)
    first = service.decide(
        tenant_id="tenant-p8",
        approval_work_item_id=WORK_ID,
        decision="APPROVE",
        decided_by="approver-s37",
        decision_comment="Approved.",
    )
    replay = service.decide(
        tenant_id="tenant-p8",
        approval_work_item_id=WORK_ID,
        decision="APPROVE",
        decided_by="approver-s37",
        decision_comment="Approved.",
    )
    assert replay == {"decision": first["decision"], "created": False}
    assert len(source.calls) == 2


@pytest.mark.parametrize(
    "changes",
    (
        {"decision": "REJECT", "decision_comment": "Rejected."},
        {"decision_comment": "A different comment."},
    ),
)
def test_s37_conflicting_terminal_replay_preserves_original(changes):
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    service, _ = _service(repository)
    service.decide(
        tenant_id="tenant-p8",
        approval_work_item_id=WORK_ID,
        decision="APPROVE",
        decided_by="approver-s37",
        decision_comment="Approved.",
    )
    request = {
        "tenant_id": "tenant-p8",
        "approval_work_item_id": WORK_ID,
        "decision": "APPROVE",
        "decided_by": "approver-s37",
        "decision_comment": "Approved.",
        **changes,
    }
    with pytest.raises(ApprovalDecisionError) as conflict:
        service.decide(**request)
    assert conflict.value.error_code == "wc.approval_decision_conflict"
    assert repository.get_decision(
        tenant_id="tenant-p8", approval_work_item_id=WORK_ID
    ) == _decision()


def test_s37_sqlalchemy_commit_replay_conflict_and_restart_projection():
    factory, engine = _factory()
    try:
        repository = SqlAlchemyApprovalWorkItemRepository(factory)
        repository.insert(_work_item())
        service, source = _service(repository)
        created = service.decide(
            tenant_id="tenant-p8",
            approval_work_item_id=WORK_ID,
            decision="APPROVE",
            decided_by="approver-s37",
            decision_comment="Approved.",
        )
        restarted = SqlAlchemyApprovalWorkItemRepository(factory)
        assert restarted.get_decision(
            tenant_id="tenant-p8", approval_work_item_id=WORK_ID
        ) == created["decision"]
        replay, _ = _service(restarted, source)
        assert replay.decide(
            tenant_id="tenant-p8",
            approval_work_item_id=WORK_ID,
            decision="APPROVE",
            decided_by="approver-s37",
            decision_comment="Approved.",
        )["created"] is False
        with pytest.raises(ApprovalDecisionError):
            replay.decide(
                tenant_id="tenant-p8",
                approval_work_item_id=WORK_ID,
                decision="REJECT",
                decided_by="approver-s37",
                decision_comment="Rejected.",
            )
        with factory() as session:
            assert session.execute(
                text("SELECT count(*) FROM wc_approval_decision")
            ).scalar_one() == 1
            row = session.execute(
                text("SELECT state, version FROM wc_approval_work_item")
            ).mappings().one()
            assert dict(row) == {"state": "APPROVED", "version": 2}
    finally:
        engine.dispose()


def test_s37_missing_item_and_stale_or_non_pending_state_fail_closed():
    repository = InMemoryApprovalWorkItemRepository()
    service, _ = _service(repository)
    with pytest.raises(ApprovalDecisionError) as missing:
        service.decide(
            tenant_id="tenant-p8",
            approval_work_item_id=WORK_ID,
            decision="APPROVE",
            decided_by="approver-s37",
        )
    assert missing.value.status_code == 404

    repository.insert(_work_item(state="CANCELLED"))
    with pytest.raises(ApprovalDecisionError) as state_conflict:
        service.decide(
            tenant_id="tenant-p8",
            approval_work_item_id=WORK_ID,
            decision="APPROVE",
            decided_by="approver-s37",
        )
    assert state_conflict.value.status_code == 409


def test_s37_repository_version_conflict_and_store_failure_are_distinct():
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    with pytest.raises(ApprovalDecisionError) as version_conflict:
        repository.commit_decision(
            decision=_decision(), outbox=_outbox(), expected_version=2
        )
    assert version_conflict.value.status_code == 409

    factory, engine = _factory(with_schema=False)
    try:
        unavailable = SqlAlchemyApprovalWorkItemRepository(factory)
        with pytest.raises(ApprovalDecisionError) as get_error:
            unavailable.get_decision(
                tenant_id="tenant-p8", approval_work_item_id=WORK_ID
            )
        assert get_error.value.status_code == 503
        assert get_error.value.retryable is True
        with pytest.raises(ApprovalDecisionError) as commit_error:
            unavailable.commit_decision(
                decision=_decision(), outbox=_outbox(), expected_version=1
            )
        assert commit_error.value.error_code == "wc.approval_decision_store_unavailable"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "change",
    (
        {"extra": True},
        {"schema_version": "v2"},
        {"tenant_id": "bad tenant"},
        {"decision_id": "bad"},
        {"approval_work_item_id": "bad"},
        {"decision": "HOLD"},
        {"decided_by": "bad principal"},
        {"decision_comment": "x" * 2001},
        {"decision_version": True},
        {"authorized_by_oa": False},
        {"oa_decision_ref": "bad ref"},
        {"authorization_revision_hash": "bad"},
        {"authorization_checked_at": "bad"},
        {"decided_at": "bad"},
    ),
)
def test_s37_invalid_decision_contract_fails_closed(change):
    decision = _decision()
    decision.update(change)
    with pytest.raises(ApprovalDecisionError) as invalid:
        validate_approval_decision(decision)
    assert invalid.value.error_code == "wc.approval_decision_invalid"


def test_s37_reject_maps_to_rejected_terminal_state():
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    rejected = _decision(
        decision="REJECT",
        decision_comment=None,
    )
    saved, created = repository.commit_decision(
        decision=rejected, outbox=_outbox(rejected), expected_version=1
    )
    assert created is True
    assert saved["decision"] == "REJECT"
    assert repository.get(
        tenant_id="tenant-p8", approval_work_item_id=WORK_ID
    )["state"] == "REJECTED"
