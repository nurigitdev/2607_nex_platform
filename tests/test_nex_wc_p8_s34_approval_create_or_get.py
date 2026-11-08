from __future__ import annotations

from pathlib import Path

import pytest
from nex_wc.approvals import (
    ApprovalWorkItemError,
    ApprovalWorkItemService,
    InMemoryApprovalWorkItemRepository,
    SqlAlchemyApprovalWorkItemRepository,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

WORK_ID = "34000000-0000-4000-8000-000000000001"


def _work_item(**overrides):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8",
        "approval_work_item_id": WORK_ID,
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-p8-s34",
        "semantic_hash": "sha256:" + "3" * 64,
        "title": "Approve protected WRITE",
        "display_safe_summary": "Create the approved voucher draft.",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-p8-s34",
        "target_approver_ref": "approver-s34",
        "target_role_ref": None,
        "target_org_scope_ref": "org-finance",
        "target_project_scope_ref": "project-p8",
        "agent_execution_id": "agent-execution-s34",
        "executable_step_id": "step-s34",
        "nsl_execution_id": "nsl-execution-s34",
        "business_operation_id": "operation-s34",
        "approval_request_id": "approval-request-p8-s34",
        "protected_request_ref": "ae-private:approval-request-p8-s34",
        "resume_target_ref": "ae-wait:approval-request-p8-s34",
        "state": "PENDING",
        "created_at": "2026-10-22T10:00:00Z",
        "expires_at": "2026-10-23T10:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
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


@pytest.mark.parametrize(
    "repository_factory",
    (InMemoryApprovalWorkItemRepository,),
)
def test_s34_exact_retry_resolves_the_original_work_item(repository_factory):
    service = ApprovalWorkItemService(repository_factory())
    first = service.create_or_get(_work_item())
    replay = service.create_or_get(
        _work_item(
            approval_work_item_id="34000000-0000-4000-8000-000000000002",
            created_at="2026-10-22T10:00:03Z",
        )
    )
    assert first["created"] is True
    assert replay["created"] is False
    assert replay["work_item"] == first["work_item"]


@pytest.mark.parametrize(
    "change",
    (
        {"semantic_hash": "sha256:" + "4" * 64},
        {"resume_target_ref": "ae-wait:different"},
        {"target_approver_ref": "different-approver"},
        {"expires_at": "2026-10-24T10:00:00Z"},
    ),
)
def test_s34_same_source_with_different_semantics_fails_closed(change):
    service = ApprovalWorkItemService(InMemoryApprovalWorkItemRepository())
    service.create_or_get(_work_item())
    with pytest.raises(ApprovalWorkItemError) as conflict:
        service.create_or_get(_work_item(**change))
    assert conflict.value.error_code == "wc.approval_work_item_idempotency_conflict"
    assert conflict.value.status_code == 409


def test_s34_primary_identity_cannot_be_reused_for_a_different_source():
    repository = InMemoryApprovalWorkItemRepository()
    repository.create_or_get(_work_item())
    with pytest.raises(ApprovalWorkItemError) as conflict:
        repository.create_or_get(
            _work_item(source_ref="approval-request-other", approval_request_id="other")
        )
    assert conflict.value.error_code == "wc.approval_work_item_conflict"


def test_s34_source_lookup_is_tenant_and_domain_scoped():
    repository = InMemoryApprovalWorkItemRepository()
    repository.create_or_get(_work_item())
    assert repository.get_by_source(
        tenant_id="tenant-p8",
        approval_domain="NSL_WRITE",
        source_ref="approval-request-p8-s34",
    ) == _work_item()
    assert repository.get_by_source(
        tenant_id="tenant-other",
        approval_domain="NSL_WRITE",
        source_ref="approval-request-p8-s34",
    ) is None


def test_s34_sqlalchemy_create_or_get_is_restart_safe_and_atomic_by_source():
    factory, engine = _factory()
    try:
        first_repository = SqlAlchemyApprovalWorkItemRepository(factory)
        first, created = first_repository.create_or_get(_work_item())
        restarted = SqlAlchemyApprovalWorkItemRepository(factory)
        replay, replay_created = restarted.create_or_get(
            _work_item(
                approval_work_item_id="34000000-0000-4000-8000-000000000002",
                created_at="2026-10-22T10:01:00Z",
            )
        )
        assert created is True
        assert replay_created is False
        assert replay == first
        assert restarted.get_by_source(
            tenant_id="tenant-p8",
            approval_domain="NSL_WRITE",
            source_ref="approval-request-p8-s34",
        ) == first
        assert restarted.get_by_source(
            tenant_id="tenant-p8",
            approval_domain="AGENT_FORMAL",
            source_ref="approval-request-p8-s34",
        ) is None
        business = _work_item(
            approval_work_item_id="34000000-0000-4000-8000-000000000003",
            approval_domain="BUSINESS_FORMAL",
            source_ref="business-operation-s34",
            approval_provider_type="EOS",
            approval_target_ref="business-operation-s34",
            agent_execution_id=None,
            executable_step_id=None,
            nsl_execution_id=None,
            approval_request_id=None,
            expires_at=None,
        )
        restarted.create_or_get(business)
        assert restarted.get_by_source(
            tenant_id="tenant-p8",
            approval_domain="BUSINESS_FORMAL",
            source_ref="business-operation-s34",
        )["expires_at"] is None
    finally:
        engine.dispose()


def test_s34_sqlalchemy_replay_conflict_and_primary_collision_fail_closed():
    factory, engine = _factory()
    try:
        repository = SqlAlchemyApprovalWorkItemRepository(factory)
        repository.create_or_get(_work_item())
        with pytest.raises(ApprovalWorkItemError) as semantic_conflict:
            repository.create_or_get(
                _work_item(semantic_hash="sha256:" + "5" * 64)
            )
        assert semantic_conflict.value.error_code == (
            "wc.approval_work_item_idempotency_conflict"
        )
        with pytest.raises(ApprovalWorkItemError) as identity_conflict:
            repository.create_or_get(
                _work_item(
                    source_ref="approval-request-other",
                    approval_request_id="approval-request-other",
                )
            )
        assert identity_conflict.value.error_code == "wc.approval_work_item_conflict"
    finally:
        engine.dispose()


def test_s34_sqlalchemy_create_or_get_maps_missing_reload_and_store_failure():
    class Result:
        rowcount = 1

        def mappings(self):
            return self

        def first(self):
            return None

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return Result()

        def commit(self):
            raise AssertionError("missing reload must fail before commit")

    missing = SqlAlchemyApprovalWorkItemRepository(lambda: Session())
    with pytest.raises(ApprovalWorkItemError) as missing_error:
        missing.create_or_get(_work_item())
    assert missing_error.value.error_code == "wc.approval_work_item_write_conflict"

    class BrokenSession(Session):
        def execute(self, *_args, **_kwargs):
            from sqlalchemy.exc import OperationalError

            raise OperationalError("INSERT", {}, Exception("offline"))

    unavailable = SqlAlchemyApprovalWorkItemRepository(lambda: BrokenSession())
    with pytest.raises(ApprovalWorkItemError) as store_error:
        unavailable.create_or_get(_work_item())
    assert store_error.value.error_code == "wc.approval_work_item_store_unavailable"
    with pytest.raises(ApprovalWorkItemError):
        unavailable.get_by_source(
            tenant_id="tenant-p8",
            approval_domain="NSL_WRITE",
            source_ref="approval-request-p8-s34",
        )


def test_s34_no_schema_or_migration_churn_is_required():
    root = Path(__file__).resolve().parents[1]
    migration = root / "database/nex-wc/migrations/1006_wc_approval_foundation.sql"
    assert "ux_wc_aw_source" in migration.read_text(encoding="utf-8")
    assert not (root / "database/nex-wc/migrations/1007_wc_approval_idempotency.sql").exists()
