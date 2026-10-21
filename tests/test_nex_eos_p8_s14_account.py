from __future__ import annotations

from datetime import date, datetime

import pytest
from nex_eos import (
    EOS_METADATA,
    AccountInput,
    EosAccountError,
    SqlAlchemyEosAccountRepository,
)
from nex_eos.app import create_eos_app
from run_migrations import load_migrations
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ACCOUNT_ID = "61000000-0000-4000-8000-000000000001"
START = date(2026, 1, 1)


@pytest.fixture
def repository() -> SqlAlchemyEosAccountRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return SqlAlchemyEosAccountRepository(sessionmaker(bind=engine))


def _account(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "account_id": ACCOUNT_ID,
        "account_code": "TRAVEL-EXPENSE",
        "name": "Travel expense",
        "category": "EXPENSE",
        "account_type": "OPERATING_EXPENSE",
        "effective_from": START,
    }
    values.update(overrides)
    return AccountInput(**values)


def test_s14_migration_declares_stable_effective_account() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2505_eos_account"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_account" in compact
    assert "unique (tenant_id, account_code)" in compact
    assert "effective_until > effective_from" in compact
    assert "credential" not in compact


def test_active_account_is_effective_only_inside_period(
    repository: SqlAlchemyEosAccountRepository,
) -> None:
    created = repository.create_account(
        _account(effective_until=date(2027, 1, 1))
    )
    assert created["version"] == 1
    assert repository.get_effective_account(
        tenant_id="tenant-a", account_id=ACCOUNT_ID, effective_at=START
    )["account_code"] == "TRAVEL-EXPENSE"
    assert repository.get_effective_account(
        tenant_id="tenant-a",
        account_id=ACCOUNT_ID,
        effective_at=date(2027, 1, 1),
    ) is None


def test_inactive_unknown_and_cross_tenant_accounts_do_not_resolve(
    repository: SqlAlchemyEosAccountRepository,
) -> None:
    repository.create_account(_account(status="INACTIVE"))
    assert repository.get_account(
        tenant_id="tenant-a", account_id=ACCOUNT_ID
    )["status"] == "INACTIVE"
    for tenant, account_id in (
        ("tenant-a", ACCOUNT_ID),
        ("tenant-b", ACCOUNT_ID),
        ("tenant-a", "61000000-0000-4000-8000-000000000002"),
    ):
        assert repository.get_effective_account(
            tenant_id=tenant,
            account_id=account_id,
            effective_at=START,
        ) is None


def test_account_code_is_unique_per_tenant(
    repository: SqlAlchemyEosAccountRepository,
) -> None:
    repository.create_account(_account())
    repository.create_account(_account(tenant_id="tenant-b"))
    with pytest.raises(EosAccountError) as conflict:
        repository.create_account(
            _account(account_id="61000000-0000-4000-8000-000000000002")
        )
    assert conflict.value.error_code == "EOS_ACCOUNT_CONFLICT"


@pytest.mark.parametrize(
    "overrides",
    (
        {"tenant_id": "bad tenant"},
        {"account_id": "bad"},
        {"account_code": "bad code"},
        {"name": " "},
        {"category": "OTHER"},
        {"account_type": "bad type"},
        {"status": "DELETED"},
        {"effective_from": datetime(2026, 1, 1)},
        {"effective_until": "2027-01-01"},
        {"effective_until": START},
        {"version": 0},
        {"version": 2},
    ),
)
def test_account_input_validation_fails_closed(
    repository: SqlAlchemyEosAccountRepository,
    overrides,
) -> None:
    with pytest.raises(EosAccountError) as error:
        repository.create_account(_account(**overrides))
    assert error.value.error_code == "EOS_ACCOUNT_INVALID"


def test_effective_date_validation_and_database_errors_are_redacted(
    repository: SqlAlchemyEosAccountRepository,
) -> None:
    with pytest.raises(EosAccountError) as invalid:
        repository.get_effective_account(
            tenant_id="tenant-a",
            account_id=ACCOUNT_ID,
            effective_at=datetime(2026, 1, 1),
        )
    assert invalid.value.error_code == "EOS_ACCOUNT_INVALID"

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private account detail")

    broken = SqlAlchemyEosAccountRepository(lambda: BrokenSession())  # type: ignore[arg-type]
    for operation in (
        lambda: broken.get_account(tenant_id="tenant-a", account_id=ACCOUNT_ID),
        lambda: broken.get_effective_account(
            tenant_id="tenant-a", account_id=ACCOUNT_ID, effective_at=START
        ),
    ):
        with pytest.raises(EosAccountError) as error:
            operation()
        assert error.value.error_code == "EOS_ACCOUNT_PERSISTENCE_FAILED"
        assert "private account detail" not in error.value.detail


def test_app_wires_account_repository_only_with_database_runtime(monkeypatch) -> None:
    base = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s14",
        "NEX_BUILD_SHA": "p8s14test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    assert create_eos_app(environ=base).state.eos_accounts is None

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
    assert isinstance(app.state.eos_accounts, SqlAlchemyEosAccountRepository)

