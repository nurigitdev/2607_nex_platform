from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from nex_eos import (
    EOS_METADATA,
    AccountInput,
    EosVoucherError,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherRepository,
    VoucherDraftInput,
    VoucherLineInput,
)
from run_migrations import load_migrations
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NVT_ID = "71000000-0000-4000-8000-000000000001"
PROJECT_ID = "72000000-0000-4000-8000-000000000001"
DEBIT_ID = "73000000-0000-4000-8000-000000000001"
CREDIT_ID = "73000000-0000-4000-8000-000000000002"
VOUCHER_ID = "74000000-0000-4000-8000-000000000001"
TX_DATE = date(2026, 10, 21)


@pytest.fixture
def repositories():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return (
        SqlAlchemyEosProjectRepository(factory),
        SqlAlchemyEosAccountRepository(factory),
        SqlAlchemyEosVoucherRepository(factory),
    )


def _seed(repositories, *, project_status="ACTIVE", credit_status="ACTIVE"):
    projects, accounts, _vouchers = repositories
    projects.create_nvt_project(
        NvtProjectInput("tenant-a", NVT_ID, "NVT-A", "NVT A")
    )
    projects.create_project(
        ProjectInput(
            "tenant-a",
            PROJECT_ID,
            "PROJECT-A",
            "Project A",
            nvt_project_id=NVT_ID,
            status=project_status,
        )
    )
    for account_id, code, category, status in (
        (DEBIT_ID, "TRAVEL", "EXPENSE", "ACTIVE"),
        (CREDIT_ID, "CASH", "ASSET", credit_status),
    ):
        accounts.create_account(
            AccountInput(
                "tenant-a",
                account_id,
                code,
                code,
                category,
                "GENERAL",
                date(2026, 1, 1),
                status=status,
            )
        )


def _line(account_id, amount, category, **overrides):
    values = {
        "account_id": account_id,
        "signed_amount": amount,
        "economic_category": category,
    }
    values.update(overrides)
    return VoucherLineInput(**values)


def _draft(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "voucher_id": VOUCHER_ID,
        "project_id": PROJECT_ID,
        "transaction_date": TX_DATE,
        "description": "Travel expense draft",
        "requester_ref": {"type": "oa.user", "id": "employee-1001"},
        "source_ref": {"type": "nsl.approval_request", "id": "approval-1001"},
        "lines": (
            _line(DEBIT_ID, Decimal("150000.00"), "TRAVEL_EXPENSE"),
            _line(
                CREDIT_ID,
                Decimal("-150000.00"),
                "CASH_SETTLEMENT",
                evidence_refs=("evidence-1",),
            ),
        ),
    }
    values.update(overrides)
    return VoucherDraftInput(**values)


def test_s15_migration_declares_voucher_aggregate() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2506_eos_voucher_draft"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_voucher_draft" in compact
    assert "create table if not exists eos_voucher_draft_line" in compact
    assert "numeric(20, 2)" in compact
    assert "signed_amount <> 0" in compact
    assert "on delete cascade" in compact


def test_balanced_decimal_draft_is_created_and_loaded(repositories) -> None:
    _seed(repositories)
    vouchers = repositories[2]
    created = vouchers.create_draft(_draft())
    loaded = vouchers.get_draft(tenant_id="tenant-a", voucher_id=VOUCHER_ID)

    assert created["state"] == "DRAFT"
    assert created["version"] == 1
    assert [line["line_no"] for line in loaded["lines"]] == [1, 2]
    assert sum((line["signed_amount"] for line in loaded["lines"]), Decimal()) == 0
    assert loaded["lines"][1]["evidence_refs"] == ["evidence-1"]
    assert vouchers.get_draft(tenant_id="tenant-b", voucher_id=VOUCHER_ID) is None


@pytest.mark.parametrize(
    ("lines", "code"),
    (
        ((), "EOS_VOUCHER_INVALID"),
        ((_line(DEBIT_ID, Decimal("1.00"), "TRAVEL"),), "EOS_VOUCHER_UNBALANCED"),
        (
            (
                _line(DEBIT_ID, Decimal("1.00"), "TRAVEL"),
                _line(CREDIT_ID, Decimal("-0.99"), "CASH"),
            ),
            "EOS_VOUCHER_UNBALANCED",
        ),
        (
            (
                _line(DEBIT_ID, 1.0, "TRAVEL"),
                _line(CREDIT_ID, Decimal("-1.00"), "CASH"),
            ),
            "EOS_VOUCHER_INVALID",
        ),
        (
            (
                _line(DEBIT_ID, Decimal("1.001"), "TRAVEL"),
                _line(CREDIT_ID, Decimal("-1.001"), "CASH"),
            ),
            "EOS_VOUCHER_INVALID",
        ),
        (
            (
                _line(DEBIT_ID, Decimal("0"), "TRAVEL"),
                _line(CREDIT_ID, Decimal("0"), "CASH"),
            ),
            "EOS_VOUCHER_INVALID",
        ),
        (
            (
                _line(DEBIT_ID, Decimal("1000000000000000000.00"), "TRAVEL"),
                _line(CREDIT_ID, Decimal("-1000000000000000000.00"), "CASH"),
            ),
            "EOS_VOUCHER_INVALID",
        ),
    ),
)
def test_zero_unbalanced_and_non_decimal_lines_are_denied(
    repositories, lines, code
) -> None:
    _seed(repositories)
    with pytest.raises(EosVoucherError) as error:
        repositories[2].create_draft(_draft(lines=lines))
    assert error.value.error_code == code


def test_project_and_account_refs_are_revalidated(repositories) -> None:
    _seed(repositories, credit_status="INACTIVE")
    vouchers = repositories[2]
    with pytest.raises(EosVoucherError) as inactive_account:
        vouchers.create_draft(_draft())
    assert inactive_account.value.error_code == "EOS_VOUCHER_ACCOUNT_NOT_EFFECTIVE"

    missing_account = "73000000-0000-4000-8000-000000000099"
    with pytest.raises(EosVoucherError) as unknown_account:
        vouchers.create_draft(
            _draft(
                lines=(
                    _line(DEBIT_ID, Decimal("1.00"), "TRAVEL"),
                    _line(missing_account, Decimal("-1.00"), "CASH"),
                )
            )
        )
    assert unknown_account.value.error_code == "EOS_VOUCHER_ACCOUNT_NOT_FOUND"

    with pytest.raises(EosVoucherError) as unknown_project:
        vouchers.create_draft(
            _draft(project_id="72000000-0000-4000-8000-000000000099")
        )
    assert unknown_project.value.error_code == "EOS_VOUCHER_PROJECT_NOT_FOUND"


def test_inactive_project_and_cross_tenant_refs_are_denied(repositories) -> None:
    _seed(repositories, project_status="INACTIVE")
    with pytest.raises(EosVoucherError) as inactive:
        repositories[2].create_draft(_draft())
    assert inactive.value.error_code == "EOS_VOUCHER_PROJECT_NOT_EFFECTIVE"

    with pytest.raises(EosVoucherError) as cross_tenant:
        repositories[2].create_draft(_draft(tenant_id="tenant-b"))
    assert cross_tenant.value.error_code == "EOS_VOUCHER_PROJECT_NOT_FOUND"


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    (
        (date(2027, 1, 1), None),
        (date(2026, 1, 1), date(2026, 10, 20)),
    ),
)
def test_project_outside_transaction_period_is_denied(
    repositories, start_date, end_date
) -> None:
    projects, accounts, vouchers = repositories
    projects.create_nvt_project(
        NvtProjectInput("tenant-a", NVT_ID, "NVT-A", "NVT A")
    )
    projects.create_project(
        ProjectInput(
            "tenant-a",
            PROJECT_ID,
            "PROJECT-A",
            "Project A",
            nvt_project_id=NVT_ID,
            start_date=start_date,
            end_date=end_date,
        )
    )
    for account_id, code, category in (
        (DEBIT_ID, "TRAVEL", "EXPENSE"),
        (CREDIT_ID, "CASH", "ASSET"),
    ):
        accounts.create_account(
            AccountInput(
                "tenant-a",
                account_id,
                code,
                code,
                category,
                "GENERAL",
                date(2026, 1, 1),
            )
        )
    with pytest.raises(EosVoucherError) as error:
        vouchers.create_draft(_draft())
    assert error.value.error_code == "EOS_VOUCHER_PROJECT_NOT_EFFECTIVE"


@pytest.mark.parametrize(
    ("effective_from", "effective_until"),
    (
        (date(2027, 1, 1), None),
        (date(2026, 1, 1), TX_DATE),
    ),
)
def test_account_outside_transaction_period_is_denied(
    repositories, effective_from, effective_until
) -> None:
    projects, accounts, vouchers = repositories
    projects.create_nvt_project(
        NvtProjectInput("tenant-a", NVT_ID, "NVT-A", "NVT A")
    )
    projects.create_project(
        ProjectInput(
            "tenant-a", PROJECT_ID, "PROJECT-A", "Project A", nvt_project_id=NVT_ID
        )
    )
    accounts.create_account(
        AccountInput(
            "tenant-a",
            DEBIT_ID,
            "TRAVEL",
            "Travel",
            "EXPENSE",
            "GENERAL",
            effective_from,
            effective_until=effective_until,
        )
    )
    accounts.create_account(
        AccountInput(
            "tenant-a",
            CREDIT_ID,
            "CASH",
            "Cash",
            "ASSET",
            "GENERAL",
            date(2026, 1, 1),
        )
    )
    with pytest.raises(EosVoucherError) as error:
        vouchers.create_draft(_draft())
    assert error.value.error_code == "EOS_VOUCHER_ACCOUNT_NOT_EFFECTIVE"


@pytest.mark.parametrize(
    "overrides",
    (
        {"voucher_id": "bad"},
        {"transaction_date": datetime(2026, 10, 21)},
        {"description": " "},
        {"requester_ref": {"type": "oa.user"}},
        {"requester_ref": {"type": "OA USER", "id": "employee-1"}},
        {"source_ref": "approval-1"},
        {"voucher_type": "bad type"},
        {"currency": "KR"},
        {"state": "SUBMITTED"},
        {"version": 0},
        {"version": 2},
    ),
)
def test_draft_validation_fails_closed(repositories, overrides) -> None:
    _seed(repositories)
    with pytest.raises(EosVoucherError) as error:
        repositories[2].create_draft(_draft(**overrides))
    assert error.value.error_code == "EOS_VOUCHER_INVALID"


def test_duplicate_voucher_is_conflict(repositories) -> None:
    _seed(repositories)
    repositories[2].create_draft(_draft())
    with pytest.raises(EosVoucherError) as conflict:
        repositories[2].create_draft(_draft())
    assert conflict.value.error_code == "EOS_VOUCHER_CONFLICT"


@pytest.mark.parametrize(
    "lines",
    (
        "not-lines",
        42,
        (object(),),
        (
            _line(
                DEBIT_ID,
                Decimal("NaN"),
                "TRAVEL",
            ),
        ),
        (
            _line(
                DEBIT_ID,
                Decimal("1E+999999999"),
                "TRAVEL",
            ),
        ),
        (
            _line(
                DEBIT_ID,
                Decimal("1.00"),
                "TRAVEL",
                evidence_refs="not-a-sequence-of-refs",
            ),
        ),
        (
            _line(
                DEBIT_ID,
                Decimal("1.00"),
                "TRAVEL",
                evidence_refs=tuple(f"evidence-{index}" for index in range(21)),
            ),
        ),
        (
            _line(
                DEBIT_ID,
                Decimal("1.00"),
                "TRAVEL",
                evidence_refs=("bad ref",),
            ),
        ),
    ),
)
def test_line_shape_decimal_and_evidence_boundaries_are_denied(
    repositories, lines
) -> None:
    _seed(repositories)
    with pytest.raises(EosVoucherError) as error:
        repositories[2].create_draft(_draft(lines=lines))
    assert error.value.error_code == "EOS_VOUCHER_INVALID"


def test_unexpected_create_database_failure_is_redacted() -> None:
    class BrokenSession:
        def execute(self, _statement, *_args):
            raise SQLAlchemyError("private voucher write detail")

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    repository = SqlAlchemyEosVoucherRepository(lambda: BrokenSession())  # type: ignore[arg-type]
    with pytest.raises(EosVoucherError) as error:
        repository.create_draft(_draft())
    assert error.value.error_code == "EOS_VOUCHER_PERSISTENCE_FAILED"
    assert "private voucher write detail" not in error.value.detail


def test_voucher_read_database_failure_is_redacted() -> None:
    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private voucher detail")

    repository = SqlAlchemyEosVoucherRepository(lambda: BrokenSession())  # type: ignore[arg-type]
    with pytest.raises(EosVoucherError) as error:
        repository.get_draft(tenant_id="tenant-a", voucher_id=VOUCHER_ID)
    assert error.value.error_code == "EOS_VOUCHER_PERSISTENCE_FAILED"
    assert "private voucher detail" not in error.value.detail
