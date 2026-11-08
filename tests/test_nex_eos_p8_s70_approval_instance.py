from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from nex_eos import (
    EOS_APPROVAL_DECISION_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_METADATA,
    EOS_ORG_UNIT_TABLE,
    EOS_PROJECT_TABLE,
    ApprovalInstanceInput,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    EosApprovalInstanceError,
    NvtProjectInput,
    OrgUnitInput,
    ProjectInput,
    SqlAlchemyEosApprovalInstanceRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosOrganizationRepository,
    SqlAlchemyEosProjectRepository,
)
from nex_eos.app import create_eos_app
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_migrations import load_migrations
from sqlalchemy import create_engine, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
TENANT = "tenant-a"
INSTANCE_ID = "70000000-0000-4000-8000-000000000001"
POLICY_ID = "70000000-0000-4000-8000-000000000002"
OPERATION_ID = "70000000-0000-4000-8000-000000000003"
ORG_ID = "70000000-0000-4000-8000-000000000004"
NVT_ID = "70000000-0000-4000-8000-000000000005"
PROJECT_ID = "70000000-0000-4000-8000-000000000006"
PAYLOAD_HASH = semantic_sha256_hash_ref({"amount": "1000.00"})
INTENT_HASH = semantic_sha256_hash_ref({"operation": "CREATE_VOUCHER_DRAFT"})


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def repository(session_factory) -> SqlAlchemyEosApprovalInstanceRepository:
    _seed_dependencies(session_factory)
    return SqlAlchemyEosApprovalInstanceRepository(
        session_factory,
        clock=lambda: NOW,
    )


def _seed_dependencies(session_factory) -> None:
    organization = SqlAlchemyEosOrganizationRepository(session_factory)
    organization.create_org_unit(
        OrgUnitInput(
            TENANT,
            ORG_ID,
            "P8-S70-FINANCE",
            "P8-S70 Finance",
            "TEAM",
            NOW - timedelta(days=1),
        )
    )
    projects = SqlAlchemyEosProjectRepository(session_factory)
    projects.create_nvt_project(
        NvtProjectInput(TENANT, NVT_ID, "P8-S70-NVT", "P8-S70 NVT")
    )
    projects.create_project(
        ProjectInput(
            TENANT,
            PROJECT_ID,
            "P8-S70-PROJECT",
            "P8-S70 Project",
            nvt_project_id=NVT_ID,
        )
    )
    SqlAlchemyEosApprovalPolicyRepository(session_factory).create_policy(
        ApprovalPolicyInput(
            tenant_id=TENANT,
            approval_policy_id=POLICY_ID,
            policy_key="finance.voucher.standard",
            name="Standard voucher approval",
            approval_domain="BUSINESS_FORMAL",
            effective_from=NOW - timedelta(days=1),
            stages=(
                ApprovalPolicyStageInput("TEAM_LEAD"),
                ApprovalPolicyStageInput("GROUP_LEAD"),
            ),
        )
    )
    with session_factory.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=OPERATION_ID,
                idempotency_key="p8-s70-operation",
                operation="CREATE_VOUCHER_DRAFT",
                payload_hash=PAYLOAD_HASH,
                commit_state="COMMITTED",
                result_json={"voucher_id": "voucher-p8-s70"},
                created_at=NOW - timedelta(minutes=1),
                committed_at=NOW - timedelta(seconds=30),
            )
        )


def _request(**overrides) -> ApprovalInstanceInput:
    values = {
        "tenant_id": TENANT,
        "approval_instance_id": INSTANCE_ID,
        "idempotency_key": "p8-s70-approval-1",
        "approval_policy_id": POLICY_ID,
        "business_operation_id": OPERATION_ID,
        "protected_operation_ref": "eos:business-operation:p8-s70",
        "payload_hash": PAYLOAD_HASH,
        "write_intent_hash": INTENT_HASH,
        "requester_ref": {"type": "oa.user", "id": "employee-1001"},
        "org_unit_id": ORG_ID,
        "project_id": PROJECT_ID,
        "correlation_id": "correlation-p8-s70",
        "causation_id": "causation-p8-s70",
        "expires_at": NOW + timedelta(days=7),
    }
    values.update(overrides)
    return ApprovalInstanceInput(**values)


def test_s70_migration_declares_instance_stage_and_append_only_decision() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2510_eos_approval_instance"
    )
    compact = " ".join(migration.sql.lower().split())

    assert "create table if not exists eos_approval_instance" in compact
    assert "create table if not exists eos_approval_stage" in compact
    assert "create table if not exists eos_approval_decision" in compact
    assert "unique (tenant_id, idempotency_key)" in compact
    assert "where state = 'active'" in compact
    assert "approval_domain = 'business_formal'" in compact
    assert "authorized_by_oa = true" in compact
    assert "credential" not in compact
    identifiers = [
        line.split()[-1]
        for line in migration.sql.splitlines()
        if "constraint " in line.lower() or "index if not exists " in line.lower()
    ]
    assert identifiers
    assert all(len(identifier) <= 63 for identifier in identifiers)


def test_creation_snapshots_policy_and_activates_only_first_stage(
    repository: SqlAlchemyEosApprovalInstanceRepository,
) -> None:
    created, was_created = repository.create_or_get_instance(_request())

    assert was_created is True
    assert created["state"] == "PENDING"
    assert created["approval_domain"] == "BUSINESS_FORMAL"
    assert created["policy_ref"]["approval_policy_id"] == POLICY_ID
    assert created["policy_ref"]["version"] == 1
    assert created["policy_ref"]["policy_hash"].startswith("sha256:")
    assert created["business_operation_id"] == OPERATION_ID
    assert created["payload_hash"] == PAYLOAD_HASH
    assert created["write_intent_hash"] == INTENT_HASH
    assert created["stage_count"] == 2
    assert [stage["state"] for stage in created["stages"]] == [
        "ACTIVE",
        "WAITING",
    ]
    expected_stage_id = str(uuid.uuid5(uuid.UUID(INSTANCE_ID), "eos.approval-stage:1"))
    assert created["stages"][0]["approval_stage_id"] == expected_stage_id
    assert (
        repository.get_active_stage(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
        )
        == created["stages"][0]
    )
    assert (
        repository.get_instance(
            tenant_id=TENANT,
            approval_instance_id=INSTANCE_ID,
        )
        == created
    )
    assert (
        repository.get_by_idempotency_key(
            tenant_id=TENANT,
            idempotency_key="p8-s70-approval-1",
        )
        == created
    )


def test_exact_replay_survives_later_policy_mutation_but_drift_is_denied(
    repository: SqlAlchemyEosApprovalInstanceRepository,
    session_factory,
) -> None:
    created, _ = repository.create_or_get_instance(_request())
    original_hash = created["policy_ref"]["policy_hash"]
    with session_factory.begin() as session:
        session.execute(
            update(EOS_APPROVAL_POLICY_TABLE)
            .where(
                EOS_APPROVAL_POLICY_TABLE.c.tenant_id == TENANT,
                EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id == POLICY_ID,
            )
            .values(policy_hash=semantic_sha256_hash_ref({"revision": 2}))
        )
        session.execute(
            update(EOS_APPROVAL_POLICY_STAGE_TABLE)
            .where(
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == TENANT,
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id == POLICY_ID,
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order == 1,
            )
            .values(position_type="CEO")
        )

    replay, was_created = repository.create_or_get_instance(_request())
    assert was_created is False
    assert replay["policy_ref"]["policy_hash"] == original_hash
    assert replay["stages"][0]["position_type"] == "TEAM_LEAD"

    with pytest.raises(EosApprovalInstanceError) as conflict:
        repository.create_or_get_instance(
            _request(protected_operation_ref="eos:business-operation:changed")
        )
    assert conflict.value.error_code == "EOS_APPROVAL_INSTANCE_REPLAY_CONFLICT"


def test_identity_collision_with_a_new_idempotency_key_is_denied(
    repository: SqlAlchemyEosApprovalInstanceRepository,
) -> None:
    repository.create_or_get_instance(_request())

    with pytest.raises(EosApprovalInstanceError) as conflict:
        repository.create_or_get_instance(
            _request(idempotency_key="p8-s70-approval-collision")
        )
    assert conflict.value.error_code == "EOS_APPROVAL_INSTANCE_CONFLICT"
    assert conflict.value.status_code == 409


def test_tenant_isolation_missing_reads_and_empty_decision_history(
    repository: SqlAlchemyEosApprovalInstanceRepository,
) -> None:
    repository.create_or_get_instance(_request())

    assert (
        repository.list_decisions(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
        == []
    )
    assert (
        repository.get_instance(tenant_id="tenant-b", approval_instance_id=INSTANCE_ID)
        is None
    )
    assert (
        repository.get_by_idempotency_key(
            tenant_id="tenant-b", idempotency_key="p8-s70-approval-1"
        )
        is None
    )
    assert (
        repository.get_active_stage(
            tenant_id="tenant-b", approval_instance_id=INSTANCE_ID
        )
        is None
    )


def test_decision_history_read_model_is_ordered_and_oa_bound(
    repository: SqlAlchemyEosApprovalInstanceRepository,
    session_factory,
) -> None:
    created, _ = repository.create_or_get_instance(_request())
    stage_id = created["stages"][0]["approval_stage_id"]
    decision_hash = semantic_sha256_hash_ref({"decision": "APPROVE"})
    auth_hash = semantic_sha256_hash_ref({"revision": "oa-r1"})
    with session_factory.begin() as session:
        session.execute(
            EOS_APPROVAL_DECISION_TABLE.insert().values(
                tenant_id=TENANT,
                approval_decision_id="70000000-0000-4000-8000-000000000007",
                approval_instance_id=INSTANCE_ID,
                approval_stage_id=stage_id,
                wc_approval_work_item_id="70000000-0000-4000-8000-000000000008",
                wc_decision_id="70000000-0000-4000-8000-000000000009",
                decision="APPROVE",
                decision_version=1,
                decided_by_ref_type="oa.user",
                decided_by_id="employee-2001",
                decision_comment="Approved",
                authorized_by_oa=True,
                oa_decision_ref="oa-decision-p8-s70",
                authorization_revision_hash=auth_hash,
                authorization_checked_at=NOW + timedelta(minutes=1),
                decided_at=NOW + timedelta(minutes=2),
                decision_hash=decision_hash,
                recorded_at=NOW + timedelta(minutes=2),
            )
        )

    history = repository.list_decisions(
        tenant_id=TENANT, approval_instance_id=INSTANCE_ID
    )
    assert history[0]["decision"] == "APPROVE"
    assert history[0]["decided_by"] == {
        "type": "oa.user",
        "id": "employee-2001",
    }
    assert history[0]["authorized_by_oa"] is True
    assert (
        repository.get_instance(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)[
            "decision_history"
        ]
        == history
    )


@pytest.mark.parametrize(
    ("column", "value", "error_code"),
    (
        ("commit_state", "PREPARED", "EOS_APPROVAL_OPERATION_NOT_COMMITTED"),
        (
            "payload_hash",
            semantic_sha256_hash_ref({"other": True}),
            "EOS_APPROVAL_PAYLOAD_MISMATCH",
        ),
    ),
)
def test_operation_binding_fails_closed(
    repository,
    session_factory,
    column,
    value,
    error_code,
) -> None:
    with session_factory.begin() as session:
        session.execute(
            update(EOS_BUSINESS_OPERATION_TABLE)
            .where(
                EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == TENANT,
                EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id == OPERATION_ID,
            )
            .values(**{column: value})
        )

    with pytest.raises(EosApprovalInstanceError) as error:
        repository.create_or_get_instance(_request())
    assert error.value.error_code == error_code
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    ("table", "id_column", "reference_id", "request_field"),
    (
        (EOS_ORG_UNIT_TABLE, "org_unit_id", ORG_ID, "org_unit_id"),
        (EOS_PROJECT_TABLE, "project_id", PROJECT_ID, "project_id"),
    ),
)
def test_inactive_business_references_are_denied(
    repository,
    session_factory,
    table,
    id_column,
    reference_id,
    request_field,
) -> None:
    with session_factory.begin() as session:
        session.execute(
            update(table)
            .where(table.c.tenant_id == TENANT, table.c[id_column] == reference_id)
            .values(status="INACTIVE")
        )

    with pytest.raises(EosApprovalInstanceError) as error:
        repository.create_or_get_instance(_request())
    assert error.value.error_code == "EOS_APPROVAL_INSTANCE_INVALID"
    assert request_field in error.value.detail


@pytest.mark.parametrize(
    ("policy_values", "error_code"),
    (
        ({"status": "INACTIVE"}, "EOS_APPROVAL_POLICY_NOT_EFFECTIVE"),
        ({"approval_domain": "NSL_WRITE"}, "EOS_APPROVAL_POLICY_NOT_EFFECTIVE"),
        (
            {"effective_until": NOW - timedelta(seconds=1)},
            "EOS_APPROVAL_POLICY_NOT_EFFECTIVE",
        ),
    ),
)
def test_non_effective_policy_is_denied(
    repository,
    session_factory,
    policy_values,
    error_code,
) -> None:
    with session_factory.begin() as session:
        session.execute(
            update(EOS_APPROVAL_POLICY_TABLE)
            .where(
                EOS_APPROVAL_POLICY_TABLE.c.tenant_id == TENANT,
                EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id == POLICY_ID,
            )
            .values(**policy_values)
        )

    with pytest.raises(EosApprovalInstanceError) as error:
        repository.create_or_get_instance(_request())
    assert error.value.error_code == error_code


@pytest.mark.parametrize(
    "overrides",
    (
        {"tenant_id": "bad tenant"},
        {"approval_instance_id": "bad"},
        {"idempotency_key": "bad key"},
        {"approval_policy_id": "bad"},
        {"business_operation_id": "bad"},
        {"protected_operation_ref": "bad ref with spaces"},
        {"payload_hash": "bad"},
        {"write_intent_hash": "bad"},
        {"requester_ref": {"type": "oa.service", "id": "caller"}},
        {"requester_ref": {"type": "oa.user"}},
        {"requester_ref": "employee-1001"},
        {"org_unit_id": "bad"},
        {"project_id": "bad"},
        {"correlation_id": "bad id"},
        {"causation_id": "bad id"},
        {"expires_at": NOW.replace(tzinfo=None)},
        {"expires_at": NOW},
    ),
)
def test_request_validation_rejects_invalid_values(repository, overrides) -> None:
    with pytest.raises(EosApprovalInstanceError) as error:
        repository.create_or_get_instance(_request(**overrides))
    assert error.value.error_code == "EOS_APPROVAL_INSTANCE_INVALID"
    assert error.value.status_code == 422


def test_missing_policy_operation_and_stages_are_denied(
    repository,
    session_factory,
) -> None:
    with pytest.raises(EosApprovalInstanceError) as missing_policy:
        repository.create_or_get_instance(
            _request(approval_policy_id="70000000-0000-4000-8000-000000000099")
        )
    assert missing_policy.value.error_code == "EOS_APPROVAL_INSTANCE_INVALID"

    with pytest.raises(EosApprovalInstanceError) as missing_operation:
        repository.create_or_get_instance(
            _request(business_operation_id="70000000-0000-4000-8000-000000000099")
        )
    assert missing_operation.value.error_code == "EOS_APPROVAL_INSTANCE_INVALID"

    with session_factory.begin() as session:
        session.execute(
            EOS_APPROVAL_POLICY_STAGE_TABLE.delete().where(
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == TENANT,
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id == POLICY_ID,
            )
        )
    with pytest.raises(EosApprovalInstanceError) as missing_stages:
        repository.create_or_get_instance(_request())
    assert missing_stages.value.error_code == "EOS_APPROVAL_POLICY_INVALID_STATE"


def test_database_errors_are_redacted(monkeypatch) -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private approval detail")

    repository = SqlAlchemyEosApprovalInstanceRepository(  # type: ignore[arg-type]
        lambda: BrokenSession()
    )
    operations = (
        lambda: repository.get_instance(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        ),
        lambda: repository.get_by_idempotency_key(
            tenant_id=TENANT, idempotency_key="p8-s70-approval-1"
        ),
        lambda: repository.get_active_stage(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        ),
        lambda: repository.list_decisions(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        ),
    )
    for operation in operations:
        with pytest.raises(EosApprovalInstanceError) as error:
            operation()
        assert error.value.error_code == "EOS_APPROVAL_INSTANCE_PERSISTENCE_FAILED"
        assert "private approval detail" not in error.value.detail

    class BrokenDatabase:
        def execute(self, _statement, *_args):
            raise SQLAlchemyError("private create detail")

    @contextmanager
    def broken_unit_of_work(_factory):
        yield SimpleNamespace(db=BrokenDatabase())

    from nex_eos import approval_instances

    monkeypatch.setattr(approval_instances, "build_unit_of_work", broken_unit_of_work)
    repository = SqlAlchemyEosApprovalInstanceRepository(  # type: ignore[arg-type]
        lambda: None, clock=lambda: NOW
    )
    with pytest.raises(EosApprovalInstanceError) as error:
        repository.create_or_get_instance(_request())
    assert error.value.error_code == "EOS_APPROVAL_INSTANCE_PERSISTENCE_FAILED"
    assert "private create detail" not in error.value.detail


def test_app_wires_instance_repository_only_with_database_runtime(monkeypatch) -> None:
    base = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s70",
        "NEX_BUILD_SHA": "p8s70test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    assert create_eos_app(environ=base).state.eos_approval_instances is None

    engine = create_engine("sqlite+pysqlite:///:memory:")
    from nex_eos import dependencies

    class Runtime:
        session_factory = sessionmaker(bind=engine)

    monkeypatch.setattr(
        dependencies, "build_eos_database_runtime", lambda **_kwargs: Runtime()
    )
    app = create_eos_app(
        environ={**base, "NEX_EOS_DATABASE_URL": "sqlite+pysqlite:///:memory:"}
    )
    assert isinstance(
        app.state.eos_approval_instances,
        SqlAlchemyEosApprovalInstanceRepository,
    )
