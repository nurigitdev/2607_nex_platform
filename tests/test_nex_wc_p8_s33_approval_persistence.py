from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from nex_wc.approvals import (
    ApprovalWorkItemError,
    InMemoryApprovalWorkItemRepository,
    SqlAlchemyApprovalWorkItemRepository,
    validate_approval_work_item,
)
from run_migrations import load_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
WORK_ID = "32000000-0000-4000-8000-000000000001"


def _work_item(**overrides):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8",
        "approval_work_item_id": WORK_ID,
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-p8-001",
        "semantic_hash": "sha256:" + "a" * 64,
        "title": "Approve voucher draft creation",
        "display_safe_summary": "Create an approved draft voucher.",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-p8-001",
        "target_approver_ref": "user-approver-001",
        "target_role_ref": None,
        "target_org_scope_ref": "org-finance",
        "target_project_scope_ref": "project-p8",
        "agent_execution_id": "agent-execution-p8-001",
        "executable_step_id": "step-p8-write-001",
        "nsl_execution_id": "nsl-execution-p8-001",
        "business_operation_id": "business-operation-p8-001",
        "approval_request_id": "approval-request-p8-001",
        "protected_request_ref": "ae-private:approval-request-p8-001",
        "resume_target_ref": "ae-wait:approval-request-p8-001",
        "state": "PENDING",
        "created_at": "2026-10-22T09:00:00Z",
        "expires_at": "2026-10-23T09:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


def _factory(*, with_schema: bool = True):
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


def test_s33_in_memory_repository_round_trip_is_tenant_scoped_and_copy_safe():
    repository = InMemoryApprovalWorkItemRepository()
    saved = repository.insert(_work_item())
    saved["title"] = "mutated"

    loaded = repository.get(tenant_id="tenant-p8", approval_work_item_id=WORK_ID)
    assert loaded == _work_item()
    assert repository.get(
        tenant_id="tenant-other", approval_work_item_id=WORK_ID
    ) is None


def test_s33_in_memory_repository_rejects_identity_and_source_duplicates():
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_work_item())
    for duplicate in (
        _work_item(),
        _work_item(approval_work_item_id="32000000-0000-4000-8000-000000000002"),
    ):
        with pytest.raises(ApprovalWorkItemError) as conflict:
            repository.insert(duplicate)
        assert conflict.value.error_code == "wc.approval_work_item_conflict"
        assert conflict.value.status_code == 409


def test_s33_sqlalchemy_repository_survives_restart_and_preserves_tenant_scope():
    factory, engine = _factory()
    try:
        saved = SqlAlchemyApprovalWorkItemRepository(factory).insert(_work_item())
        restarted = SqlAlchemyApprovalWorkItemRepository(factory)
        assert saved == _work_item()
        assert restarted.get(
            tenant_id="tenant-p8", approval_work_item_id=WORK_ID
        ) == _work_item()
        assert restarted.get(
            tenant_id="tenant-other", approval_work_item_id=WORK_ID
        ) is None
        no_expiry = _work_item(
            approval_work_item_id="32000000-0000-4000-8000-000000000003",
            approval_domain="BUSINESS_FORMAL",
            source_ref="business-operation-p8-003",
            approval_provider_type="EOS",
            approval_target_ref="business-operation-p8-003",
            agent_execution_id=None,
            executable_step_id=None,
            nsl_execution_id=None,
            approval_request_id=None,
            expires_at=None,
        )
        assert restarted.insert(no_expiry)["expires_at"] is None
    finally:
        engine.dispose()


def test_s33_sqlalchemy_repository_maps_unique_and_store_failures():
    factory, engine = _factory()
    try:
        repository = SqlAlchemyApprovalWorkItemRepository(factory)
        repository.insert(_work_item())
        with pytest.raises(ApprovalWorkItemError) as duplicate:
            repository.insert(_work_item())
        assert duplicate.value.error_code == "wc.approval_work_item_conflict"
    finally:
        engine.dispose()

    missing, missing_engine = _factory(with_schema=False)
    try:
        unavailable = SqlAlchemyApprovalWorkItemRepository(missing)
        with pytest.raises(ApprovalWorkItemError) as insert_error:
            unavailable.insert(_work_item())
        assert insert_error.value.status_code == 503
        assert insert_error.value.retryable is True
        with pytest.raises(ApprovalWorkItemError) as get_error:
            unavailable.get(tenant_id="tenant-p8", approval_work_item_id=WORK_ID)
        assert get_error.value.error_code == "wc.approval_work_item_store_unavailable"
    finally:
        missing_engine.dispose()


def test_s33_sqlalchemy_repository_rejects_missing_reload():
    class Result:
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

    repository = SqlAlchemyApprovalWorkItemRepository(lambda: Session())
    with pytest.raises(ApprovalWorkItemError) as error:
        repository.insert(_work_item())
    assert error.value.error_code == "wc.approval_work_item_write_conflict"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(extra="blocked"),
        lambda value: value.pop("tenant_id"),
        lambda value: value.update(schema_version="v2"),
        lambda value: value.update(tenant_id="invalid tenant"),
        lambda value: value.update(approval_work_item_id="not-a-uuid"),
        lambda value: value.update(approval_domain="OTHER"),
        lambda value: value.update(approval_provider_type="EOS"),
        lambda value: value.update(source_ref=""),
        lambda value: value.update(title="x" * 301),
        lambda value: value.update(display_safe_summary=""),
        lambda value: value.update(semantic_hash="bad"),
        lambda value: value.update(approval_request_id=None),
        lambda value: value.update(state="CREATED"),
        lambda value: value.update(created_at="not-a-time"),
        lambda value: value.update(created_at="2026-10-22T09:00:00"),
        lambda value: value.update(expires_at="2026-10-21T09:00:00Z"),
        lambda value: value.update(version=True),
    ),
)
def test_s33_invalid_approval_work_items_fail_closed(mutate):
    value = _work_item()
    mutate(value)
    with pytest.raises(ApprovalWorkItemError) as error:
        validate_approval_work_item(value)
    assert error.value.error_code == "wc.approval_work_item_invalid"


def test_s33_domain_bindings_and_datetime_objects_are_admitted():
    agent = _work_item(
        approval_domain="AGENT_FORMAL",
        approval_provider_type="AGENT",
        nsl_execution_id=None,
        approval_request_id=None,
        created_at=datetime(2026, 10, 22, 9, tzinfo=UTC),
        expires_at=None,
    )
    business = _work_item(
        approval_domain="BUSINESS_FORMAL",
        approval_provider_type="EOS",
        agent_execution_id=None,
        executable_step_id=None,
        nsl_execution_id=None,
        approval_request_id=None,
        created_at=datetime(2026, 10, 22, 9, tzinfo=UTC).replace(tzinfo=None),
    )
    assert validate_approval_work_item(agent)["created_at"].endswith("Z")
    with pytest.raises(ApprovalWorkItemError) as timezone_error:
        validate_approval_work_item(business)
    assert "timezone" in str(timezone_error.value)
    with pytest.raises(ApprovalWorkItemError):
        validate_approval_work_item(None)  # type: ignore[arg-type]


def test_s33_migration_adds_separate_approval_aggregate_without_altering_delegation():
    migrations = load_migrations("nex-wc")
    inventory = sorted(
        path.stem for path in (ROOT / "database/nex-wc/migrations").glob("*.sql")
    )
    assert [migration.version for migration in migrations] == inventory
    sql = next(
        migration.sql
        for migration in migrations
        if migration.version == "1006_wc_approval_foundation"
    )
    for table in (
        "wc_approval_work_item",
        "wc_approval_decision",
        "wc_approval_outbox",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    for existing in ("wc_work_item", "wc_claim", "wc_assignment"):
        assert f"ALTER TABLE {existing}" not in sql
    identifiers = (
        "wc_approval_work_item",
        "wc_approval_decision",
        "wc_approval_outbox",
        "ux_wc_aw_source",
        "ck_wc_aw_provider_domain",
        "ck_wc_aw_domain_binding",
        "ix_wc_aw_inbox",
        "ix_wc_aw_scope",
        "fk_wc_ad_work",
        "ux_wc_ad_version",
        "ix_wc_ad_work_time",
        "fk_wc_ao_work",
        "fk_wc_ao_decision",
        "ux_wc_ao_event",
        "ix_wc_ao_delivery",
    )
    assert all(len(identifier) < 63 for identifier in identifiers)
    assert "raw_token" not in sql
    assert "access_token" not in sql
