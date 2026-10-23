from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from nex_eos import (
    EOS_METADATA,
    AccountInput,
    ApprovalPolicyInput,
    ApprovalPolicySelection,
    ApprovalPolicyStageInput,
    EosApprovalPolicyError,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosProjectRepository,
)
from nex_eos.app import create_eos_app
from run_migrations import load_migrations
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

POLICY_ID = "a1000000-0000-4000-8000-000000000001"
POLICY_ID_2 = "a1000000-0000-4000-8000-000000000002"
NVT_ID = "a2000000-0000-4000-8000-000000000001"
PROJECT_ID = "a3000000-0000-4000-8000-000000000001"
ACCOUNT_ID = "a4000000-0000-4000-8000-000000000001"
START = datetime(2026, 1, 1, tzinfo=UTC)


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
def repository(session_factory) -> SqlAlchemyEosApprovalPolicyRepository:
    return SqlAlchemyEosApprovalPolicyRepository(session_factory)


def _policy(**overrides) -> ApprovalPolicyInput:
    values = {
        "tenant_id": "tenant-a",
        "approval_policy_id": POLICY_ID,
        "policy_key": "finance.voucher.standard",
        "name": "Standard voucher approval",
        "approval_domain": "BUSINESS_FORMAL",
        "effective_from": START,
        "stages": (
            ApprovalPolicyStageInput("TEAM_LEAD"),
            ApprovalPolicyStageInput("GROUP_LEAD"),
        ),
    }
    values.update(overrides)
    return ApprovalPolicyInput(**values)


def _selection(**overrides) -> ApprovalPolicySelection:
    values = {
        "tenant_id": "tenant-a",
        "approval_domain": "BUSINESS_FORMAL",
        "risk_level": "HIGH",
        "amount": Decimal("250.00"),
        "transaction_type": "FINANCE.CREATE_VOUCHER_DRAFT",
        "effective_at": START,
    }
    values.update(overrides)
    return ApprovalPolicySelection(**values)


def _seed_refs(session_factory) -> None:
    projects = SqlAlchemyEosProjectRepository(session_factory)
    projects.create_nvt_project(
        NvtProjectInput("tenant-a", NVT_ID, "P8-S69-NVT", "P8-S69 NVT")
    )
    projects.create_project(
        ProjectInput(
            "tenant-a",
            PROJECT_ID,
            "P8-S69-PROJECT",
            "P8-S69 Project",
            nvt_project_id=NVT_ID,
        )
    )
    SqlAlchemyEosAccountRepository(session_factory).create_account(
        AccountInput(
            "tenant-a",
            ACCOUNT_ID,
            "P8-S69-EXPENSE",
            "P8-S69 expense",
            "EXPENSE",
            "OPERATING_EXPENSE",
            date(2026, 1, 1),
        )
    )


def test_s69_migration_declares_policy_and_ordered_stage_storage() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2509_eos_approval_policy"
    )
    compact = " ".join(migration.sql.lower().split())

    assert "create table if not exists eos_approval_policy" in compact
    assert "create table if not exists eos_approval_policy_stage" in compact
    assert "unique (tenant_id, policy_key, version)" in compact
    assert "stage_order between 1 and 5" in compact
    assert "quorum_count > 0" in compact
    assert "requester_excluded" in compact
    assert "credential" not in compact


def test_policy_round_trip_preserves_hash_selectors_and_ordered_stages(
    repository: SqlAlchemyEosApprovalPolicyRepository,
) -> None:
    created = repository.create_policy(
        _policy(
            risk_level="HIGH",
            minimum_amount=Decimal("100.00"),
            maximum_amount=Decimal("1000.00"),
            transaction_type="FINANCE.CREATE_VOUCHER_DRAFT",
        )
    )

    assert created["selector"] == {
        "risk_level": "HIGH",
        "minimum_amount": "100.00",
        "maximum_amount": "1000.00",
        "project_id": None,
        "account_id": None,
        "transaction_type": "FINANCE.CREATE_VOUCHER_DRAFT",
    }
    assert [stage["position_type"] for stage in created["stages"]] == [
        "TEAM_LEAD",
        "GROUP_LEAD",
    ]
    assert created["policy_hash"].startswith("sha256:")
    assert (
        repository.get_policy(tenant_id="tenant-a", approval_policy_id=POLICY_ID)
        == created
    )
    assert (
        repository.get_policy(tenant_id="tenant-b", approval_policy_id=POLICY_ID)
        is None
    )


def test_resolution_prefers_more_specific_policy_and_uses_half_open_amounts(
    repository: SqlAlchemyEosApprovalPolicyRepository,
    session_factory,
) -> None:
    _seed_refs(session_factory)
    repository.create_policy(
        _policy(
            approval_policy_id=POLICY_ID,
            policy_key="finance.voucher.fallback",
            stages=(ApprovalPolicyStageInput("PART_LEAD"),),
        )
    )
    repository.create_policy(
        _policy(
            approval_policy_id=POLICY_ID_2,
            policy_key="finance.voucher.project-expense",
            risk_level="HIGH",
            minimum_amount=Decimal("100.00"),
            maximum_amount=Decimal("1000.00"),
            project_id=PROJECT_ID,
            account_id=ACCOUNT_ID,
            transaction_type="FINANCE.CREATE_VOUCHER_DRAFT",
        )
    )

    exact = repository.resolve_policy(
        _selection(project_id=PROJECT_ID, account_ids=(ACCOUNT_ID, ACCOUNT_ID))
    )
    assert exact["approval_policy_id"] == POLICY_ID_2
    assert exact["stages"][0]["position_type"] == "TEAM_LEAD"

    assert (
        repository.resolve_policy(
            _selection(
                project_id=PROJECT_ID,
                account_ids=(ACCOUNT_ID,),
                amount=Decimal("1000.00"),
            )
        )["approval_policy_id"]
        == POLICY_ID
    )
    assert (
        repository.resolve_policy(_selection(account_ids=()))["approval_policy_id"]
        == POLICY_ID
    )
    assert (
        repository.resolve_policy(_selection(effective_at=START - timedelta(seconds=1)))
        is None
    )


def test_inactive_cross_tenant_and_expired_policies_do_not_match(
    repository: SqlAlchemyEosApprovalPolicyRepository,
) -> None:
    repository.create_policy(
        _policy(status="INACTIVE", effective_until=START + timedelta(days=1))
    )
    assert repository.resolve_policy(_selection()) is None
    assert repository.resolve_policy(_selection(tenant_id="tenant-b")) is None
    assert (
        repository.resolve_policy(_selection(effective_at=START + timedelta(days=1)))
        is None
    )


def test_equal_specificity_is_ambiguous_and_fails_closed(
    repository: SqlAlchemyEosApprovalPolicyRepository,
) -> None:
    repository.create_policy(_policy(risk_level="HIGH"))
    repository.create_policy(
        _policy(
            approval_policy_id=POLICY_ID_2,
            policy_key="finance.voucher.other",
            risk_level="HIGH",
        )
    )

    with pytest.raises(EosApprovalPolicyError) as denied:
        repository.resolve_policy(_selection())
    assert denied.value.error_code == "EOS_APPROVAL_POLICY_AMBIGUOUS"
    assert denied.value.status_code == 409


def test_policy_identity_conflict_and_reference_validation_fail_closed(
    repository: SqlAlchemyEosApprovalPolicyRepository,
) -> None:
    repository.create_policy(_policy())
    with pytest.raises(EosApprovalPolicyError) as conflict:
        repository.create_policy(
            _policy(
                approval_policy_id=POLICY_ID_2,
                name="Conflicting version",
            )
        )
    assert conflict.value.error_code == "EOS_APPROVAL_POLICY_CONFLICT"

    with pytest.raises(EosApprovalPolicyError) as missing:
        repository.create_policy(
            _policy(
                approval_policy_id=POLICY_ID_2,
                policy_key="finance.voucher.missing-project",
                project_id=PROJECT_ID,
            )
        )
    assert missing.value.error_code == "EOS_APPROVAL_POLICY_REFERENCE_NOT_FOUND"


@pytest.mark.parametrize(
    "overrides",
    (
        {"tenant_id": "bad tenant"},
        {"approval_policy_id": "bad"},
        {"policy_key": "bad key"},
        {"name": " "},
        {"approval_domain": "UNKNOWN"},
        {"effective_from": START.replace(tzinfo=None)},
        {"effective_until": START},
        {"version": 0},
        {"risk_level": "EXTREME"},
        {"minimum_amount": 1},
        {"minimum_amount": Decimal("-1.00")},
        {
            "minimum_amount": Decimal("10.00"),
            "maximum_amount": Decimal("10.00"),
        },
        {"project_id": "bad"},
        {"account_id": "bad"},
        {"transaction_type": "bad type"},
        {"status": "DELETED"},
        {"stages": ()},
        {"stages": "TEAM_LEAD"},
        {"stages": ("TEAM_LEAD",)},
        {"stages": (ApprovalPolicyStageInput("UNKNOWN"),)},
        {"stages": (ApprovalPolicyStageInput("TEAM_LEAD", quorum_count=2),)},
        {
            "stages": (
                ApprovalPolicyStageInput(
                    "TEAM_LEAD", separation_policy="SAME_REQUESTER_ALLOWED"
                ),
            )
        },
        {
            "stages": (
                ApprovalPolicyStageInput("GROUP_LEAD"),
                ApprovalPolicyStageInput("TEAM_LEAD"),
            )
        },
        {
            "stages": (
                ApprovalPolicyStageInput("TEAM_LEAD"),
                ApprovalPolicyStageInput("TEAM_LEAD"),
            )
        },
    ),
)
def test_policy_validation_rejects_invalid_semantics(
    repository: SqlAlchemyEosApprovalPolicyRepository, overrides
) -> None:
    with pytest.raises(EosApprovalPolicyError) as error:
        repository.create_policy(_policy(**overrides))
    assert error.value.error_code == "EOS_APPROVAL_POLICY_INVALID"
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    (
        {"tenant_id": "bad tenant"},
        {"approval_domain": "UNKNOWN"},
        {"risk_level": "UNKNOWN"},
        {"amount": 1},
        {"amount": Decimal("1.001")},
        {"amount": Decimal("1e1000000")},
        {"transaction_type": "bad type"},
        {"effective_at": START.replace(tzinfo=None)},
        {"project_id": "bad"},
        {"account_ids": "bad"},
        {"account_ids": ("bad",)},
    ),
)
def test_selection_validation_rejects_invalid_semantics(
    repository: SqlAlchemyEosApprovalPolicyRepository, overrides
) -> None:
    with pytest.raises(EosApprovalPolicyError) as error:
        repository.resolve_policy(_selection(**overrides))
    assert error.value.error_code == "EOS_APPROVAL_POLICY_INVALID"


def test_database_errors_are_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private policy detail")

    repository = SqlAlchemyEosApprovalPolicyRepository(  # type: ignore[arg-type]
        lambda: BrokenSession()
    )
    for operation in (
        lambda: repository.get_policy(
            tenant_id="tenant-a", approval_policy_id=POLICY_ID
        ),
        lambda: repository.resolve_policy(_selection()),
    ):
        with pytest.raises(EosApprovalPolicyError) as error:
            operation()
        assert error.value.error_code == "EOS_APPROVAL_POLICY_PERSISTENCE_FAILED"
        assert "private policy detail" not in error.value.detail


def test_create_database_error_is_redacted(monkeypatch) -> None:
    from contextlib import contextmanager

    from nex_eos import approval_policies

    class BrokenDatabase:
        def execute(self, _statement, *_args):
            raise SQLAlchemyError("private create detail")

    @contextmanager
    def broken_unit_of_work(_factory):
        yield SimpleNamespace(db=BrokenDatabase())

    monkeypatch.setattr(approval_policies, "build_unit_of_work", broken_unit_of_work)
    repository = SqlAlchemyEosApprovalPolicyRepository(lambda: None)  # type: ignore[arg-type]

    with pytest.raises(EosApprovalPolicyError) as error:
        repository.create_policy(_policy())
    assert error.value.error_code == "EOS_APPROVAL_POLICY_PERSISTENCE_FAILED"
    assert "private create detail" not in error.value.detail


def test_app_wires_policy_repository_only_with_database_runtime(monkeypatch) -> None:
    base = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s69",
        "NEX_BUILD_SHA": "p8s69test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    assert create_eos_app(environ=base).state.eos_approval_policies is None

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
        app.state.eos_approval_policies, SqlAlchemyEosApprovalPolicyRepository
    )
