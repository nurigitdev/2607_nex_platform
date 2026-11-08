from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionError,
    ApprovalDecisionService,
    InMemoryApprovalWorkItemRepository,
    SqlAlchemyApprovalWorkItemRepository,
    validate_approval_event,
    validate_approval_outbox,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

WORK_ID = "38000000-0000-4000-8000-000000000001"
DECISION_ID = "38100000-0000-4000-8000-000000000001"
EVENT_ID = "38200000-0000-4000-8000-000000000001"
OUTBOX_ID = "38300000-0000-4000-8000-000000000001"


def _work_item(**overrides):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8",
        "approval_work_item_id": WORK_ID,
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-s38",
        "semantic_hash": "sha256:" + "8" * 64,
        "title": "Approve protected WRITE",
        "display_safe_summary": "Create the approved voucher draft.",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-s38",
        "target_approver_ref": "approver-s38",
        "target_role_ref": None,
        "target_org_scope_ref": "org-finance",
        "target_project_scope_ref": "project-p8",
        "agent_execution_id": "agent-execution-s38",
        "executable_step_id": "step-s38",
        "nsl_execution_id": "nsl-execution-s38",
        "business_operation_id": "operation-s38",
        "approval_request_id": "approval-request-s38",
        "protected_request_ref": "ae-private:approval-request-s38",
        "resume_target_ref": "ae-wait:approval-request-s38",
        "state": "PENDING",
        "created_at": "2026-10-22T13:00:00Z",
        "expires_at": "2026-10-23T13:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


class _AuthorizationSource:
    def effective_authorization(self, **_kwargs):
        return {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s38",
            "scopes": ["approval:decide"],
            "revision_hash": "b" * 64,
            "decision_ref": "oa-decision-s38",
        }


def _service(repository):
    return ApprovalDecisionService(
        repository,
        authorizer=ApprovalDecisionAuthorizer(
            _AuthorizationSource(),
            clock=lambda: datetime(2026, 10, 22, 13, 29, 59, tzinfo=UTC),
        ),
        id_factory=lambda: DECISION_ID,
        event_id_factory=lambda: EVENT_ID,
        outbox_id_factory=lambda: OUTBOX_ID,
        clock=lambda: datetime(2026, 10, 22, 13, 30, tzinfo=UTC),
    )


def _decision():
    return {
        "schema_version": "wc_approval_decision.v1",
        "tenant_id": "tenant-p8",
        "decision_id": DECISION_ID,
        "approval_work_item_id": WORK_ID,
        "decision": "APPROVE",
        "decided_by": "approver-s38",
        "decision_comment": None,
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-decision-s38",
        "authorization_revision_hash": "sha256:" + "b" * 64,
        "authorization_checked_at": "2026-10-22T13:29:59Z",
        "decided_at": "2026-10-22T13:30:00Z",
    }


def _event(**overrides):
    value = {
        "schema_version": "wc_approval_event.v1",
        "tenant_id": "tenant-p8",
        "event_id": EVENT_ID,
        "event_type": "NSL_APPROVAL_DECIDED",
        "approval_work_item_id": WORK_ID,
        "decision_id": DECISION_ID,
        "approval_domain": "NSL_WRITE",
        "decision": "APPROVE",
        "decided_by": "approver-s38",
        "oa_decision_ref": "oa-decision-s38",
        "occurred_at": "2026-10-22T13:30:00Z",
        "correlation_id": WORK_ID,
        "causation_id": WORK_ID,
    }
    value.update(overrides)
    return value


def _outbox(**overrides):
    value = {
        "tenant_id": "tenant-p8",
        "outbox_id": OUTBOX_ID,
        "event_id": EVENT_ID,
        "approval_work_item_id": WORK_ID,
        "decision_id": DECISION_ID,
        "event_type": "NSL_APPROVAL_DECIDED",
        "event_payload": _event(),
        "delivery_state": "PENDING",
        "enqueued_job_id": None,
        "created_at": "2026-10-22T13:30:00Z",
        "updated_at": "2026-10-22T13:30:00Z",
    }
    value.update(overrides)
    return value


def _factory(*, broken_outbox=False):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    outbox_check = " CHECK (event_type = 'NEVER')" if broken_outbox else ""
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
        connection.execute(text(f"""
            CREATE TABLE wc_approval_outbox (
                tenant_id TEXT NOT NULL,
                outbox_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                approval_work_item_id TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                event_type TEXT NOT NULL{outbox_check},
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


def test_s38_decision_creates_one_domain_exact_pending_event_and_replay_does_not_duplicate():
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    service = _service(repository)
    first = service.decide(
        tenant_id="tenant-p8",
        approval_work_item_id=WORK_ID,
        decision="APPROVE",
        decided_by="approver-s38",
    )
    replay = service.decide(
        tenant_id="tenant-p8",
        approval_work_item_id=WORK_ID,
        decision="APPROVE",
        decided_by="approver-s38",
    )
    pending = repository.list_pending_approval_events(limit=10)
    assert first["created"] is True
    assert replay["created"] is False
    assert len(pending) == 1
    assert pending[0] == _outbox()
    assert "token" not in str(pending[0]).lower()


@pytest.mark.parametrize(
    "domain,provider,event_type,bindings",
    (
        (
            "AGENT_FORMAL",
            "AGENT",
            "AGENT_FORMAL_APPROVAL_DECIDED",
            {"nsl_execution_id": None, "approval_request_id": None},
        ),
        (
            "BUSINESS_FORMAL",
            "EOS",
            "BUSINESS_FORMAL_APPROVAL_DECIDED",
            {
                "agent_execution_id": None,
                "executable_step_id": None,
                "nsl_execution_id": None,
                "approval_request_id": None,
            },
        ),
    ),
)
def test_s38_event_type_is_determined_by_approval_domain(
    domain, provider, event_type, bindings
):
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(
        _work_item(approval_domain=domain, approval_provider_type=provider, **bindings)
    )
    _service(repository).decide(
        tenant_id="tenant-p8",
        approval_work_item_id=WORK_ID,
        decision="APPROVE",
        decided_by="approver-s38",
    )
    event = repository.list_pending_approval_events(limit=1)[0]
    assert event["event_type"] == event_type
    assert event["event_payload"]["event_type"] == event_type
    assert event["event_payload"]["approval_domain"] == domain


def test_s38_sqlalchemy_outbox_is_restart_safe_and_tenant_scoped():
    factory, engine = _factory()
    try:
        repository = SqlAlchemyApprovalWorkItemRepository(factory)
        repository.insert(_work_item())
        _service(repository).decide(
            tenant_id="tenant-p8",
            approval_work_item_id=WORK_ID,
            decision="APPROVE",
            decided_by="approver-s38",
        )
        restarted = SqlAlchemyApprovalWorkItemRepository(factory)
        assert restarted.list_pending_approval_events(limit=1) == [_outbox()]
        with factory() as session:
            assert session.execute(
                text("SELECT count(*) FROM wc_approval_decision")
            ).scalar_one() == 1
            assert session.execute(
                text("SELECT count(*) FROM wc_approval_outbox")
            ).scalar_one() == 1
    finally:
        engine.dispose()


def test_s38_outbox_insert_failure_rolls_back_decision_and_projection():
    factory, engine = _factory(broken_outbox=True)
    try:
        repository = SqlAlchemyApprovalWorkItemRepository(factory)
        repository.insert(_work_item())
        with pytest.raises(ApprovalDecisionError):
            _service(repository).decide(
                tenant_id="tenant-p8",
                approval_work_item_id=WORK_ID,
                decision="APPROVE",
                decided_by="approver-s38",
            )
        with factory() as session:
            assert session.execute(
                text("SELECT count(*) FROM wc_approval_decision")
            ).scalar_one() == 0
            assert session.execute(
                text("SELECT count(*) FROM wc_approval_outbox")
            ).scalar_one() == 0
            row = session.execute(
                text("SELECT state, version FROM wc_approval_work_item")
            ).mappings().one()
            assert dict(row) == {"state": "PENDING", "version": 1}
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "change",
    (
        {"schema_version": "v2"},
        {"event_id": "bad"},
        {"event_type": "BUSINESS_FORMAL_APPROVAL_DECIDED"},
        {"approval_domain": "UNKNOWN"},
        {"decision": "HOLD"},
        {"correlation_id": "bad ref"},
        {"occurred_at": "bad"},
    ),
)
def test_s38_invalid_approval_event_fails_closed(change):
    event = _event(**change)
    with pytest.raises(ApprovalDecisionError):
        validate_approval_event(event)


@pytest.mark.parametrize(
    "change",
    (
        {"extra": True},
        {"tenant_id": "tenant-other"},
        {"outbox_id": "bad"},
        {"event_id": "38200000-0000-4000-8000-000000000002"},
        {"event_type": "AGENT_FORMAL_APPROVAL_DECIDED"},
        {"delivery_state": "UNKNOWN"},
        {"enqueued_job_id": "bad ref"},
        {"created_at": "bad"},
    ),
)
def test_s38_invalid_approval_outbox_fails_closed(change):
    outbox = _outbox(**change)
    with pytest.raises(ApprovalDecisionError):
        validate_approval_outbox(outbox, decision=_decision())


@pytest.mark.parametrize("limit", (0, 1001, True))
def test_s38_pending_list_limit_is_bounded(limit):
    with pytest.raises(ApprovalDecisionError):
        InMemoryApprovalWorkItemRepository().list_pending_approval_events(limit=limit)
