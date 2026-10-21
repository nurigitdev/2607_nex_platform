from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_METADATA,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    EosVoucherVerificationError,
    SqlAlchemyEosVoucherVerificationQuery,
    create_eos_app,
)
from nex_eos import voucher_verification as module
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

OPERATION_ID = "86000000-0000-4000-8000-000000000001"
VOUCHER_ID = "84000000-0000-4000-8000-000000000001"
PROJECT_ID = "82000000-0000-4000-8000-000000000001"
DEBIT_ID = "83000000-0000-4000-8000-000000000001"
CREDIT_ID = "83000000-0000-4000-8000-000000000002"
NOW = datetime(2026, 10, 21, 1, 2, 3, tzinfo=UTC)


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed(factory, *, tenant="tenant-a", state="COMMITTED", operation_voucher=VOUCHER_ID, amounts=("10.00", "-10.00")):
    with factory.begin() as session:
        session.execute(
            EOS_VOUCHER_DRAFT_TABLE.insert().values(
                tenant_id=tenant,
                voucher_id=VOUCHER_ID,
                project_id=PROJECT_ID,
                voucher_type="GENERAL",
                currency="KRW",
                transaction_date=date(2026, 10, 21),
                description="Verified Voucher",
                requester_ref_type="oa.user",
                requester_id="employee-1001",
                source_ref_type="nsl.approval_request",
                source_id="approval-1001",
                state="DRAFT",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_VOUCHER_DRAFT_LINE_TABLE.insert(),
            [
                {
                    "tenant_id": tenant,
                    "voucher_id": VOUCHER_ID,
                    "line_no": index,
                    "account_id": account,
                    "signed_amount": Decimal(amount),
                    "economic_category": category,
                    "description": None,
                    "evidence_refs": ["approval-1001"],
                }
                for index, (account, amount, category) in enumerate(
                    ((DEBIT_ID, amounts[0], "TRAVEL"), (CREDIT_ID, amounts[1], "CASH")),
                    start=1,
                )
            ],
        )
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=tenant,
                business_operation_id=OPERATION_ID,
                idempotency_key="verify-1",
                operation="FINANCE.CREATE_VOUCHER_DRAFT",
                payload_hash="sha256:" + "a" * 64,
                commit_state=state,
                result_json={"voucher_id": operation_voucher},
                created_at=NOW,
                committed_at=NOW,
            )
        )


def test_verification_returns_stable_state_and_executes_selects_only(database):
    engine, factory = database
    _seed(factory)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.strip().split(None, 1)[0].upper())

    event.listen(engine, "before_cursor_execute", capture)
    first = SqlAlchemyEosVoucherVerificationQuery(factory).verify(
        tenant_id="tenant-a", voucher_id=VOUCHER_ID, business_operation_id=OPERATION_ID
    )
    second = SqlAlchemyEosVoucherVerificationQuery(factory).verify(
        tenant_id="tenant-a", voucher_id=VOUCHER_ID, business_operation_id=OPERATION_ID
    )
    event.remove(engine, "before_cursor_execute", capture)

    assert first == second
    assert first["line_count"] == 2
    assert first["attachment_count"] == 0
    assert first["balance"] == "0.00"
    assert first["stable_business_state_hash"].startswith("sha256:")
    assert statements and set(statements) == {"SELECT"}


@pytest.mark.parametrize(
    "tenant,state,operation_voucher,error_code,status",
    (
        ("tenant-b", "COMMITTED", VOUCHER_ID, "EOS_VOUCHER_VERIFICATION_NOT_FOUND", 404),
        ("tenant-a", "PENDING", VOUCHER_ID, "EOS_VOUCHER_VERIFICATION_BINDING_INVALID", 409),
        ("tenant-a", "COMMITTED", "84000000-0000-4000-8000-000000000099", "EOS_VOUCHER_VERIFICATION_BINDING_INVALID", 409),
    ),
)
def test_cross_tenant_uncommitted_and_mismatched_binding_fail_closed(
    database, tenant, state, operation_voucher, error_code, status
):
    _engine, factory = database
    _seed(
        factory,
        tenant=tenant,
        state=state,
        operation_voucher=operation_voucher,
    )
    request_tenant = "tenant-a" if tenant == "tenant-b" else tenant
    with pytest.raises(EosVoucherVerificationError) as error:
        SqlAlchemyEosVoucherVerificationQuery(factory).verify(
            tenant_id=request_tenant,
            voucher_id=VOUCHER_ID,
            business_operation_id=OPERATION_ID,
        )
    assert error.value.error_code == error_code
    assert error.value.status_code == status


def test_unbalanced_or_missing_lines_are_invalid_persisted_state(database):
    _engine, factory = database
    _seed(factory, amounts=("10.00", "-9.00"))
    query = SqlAlchemyEosVoucherVerificationQuery(factory)
    with pytest.raises(EosVoucherVerificationError) as unbalanced:
        query.verify(tenant_id="tenant-a", voucher_id=VOUCHER_ID, business_operation_id=OPERATION_ID)
    assert unbalanced.value.status_code == 503
    with factory.begin() as session:
        session.execute(EOS_VOUCHER_DRAFT_LINE_TABLE.delete())
    with pytest.raises(EosVoucherVerificationError, match="no persisted lines"):
        query.verify(tenant_id="tenant-a", voucher_id=VOUCHER_ID, business_operation_id=OPERATION_ID)


@pytest.mark.parametrize(
    "tenant,voucher,operation",
    (("bad value", VOUCHER_ID, OPERATION_ID), ("tenant-a", "bad", OPERATION_ID), ("tenant-a", VOUCHER_ID, "bad")),
)
def test_verification_identity_validation(database, tenant, voucher, operation):
    _engine, factory = database
    with pytest.raises(EosVoucherVerificationError) as error:
        SqlAlchemyEosVoucherVerificationQuery(factory).verify(
            tenant_id=tenant, voucher_id=voucher, business_operation_id=operation
        )
    assert error.value.status_code == 422


def test_database_failure_is_retryable_and_redacted(database, monkeypatch):
    _engine, factory = database
    query = SqlAlchemyEosVoucherVerificationQuery(factory)

    class Broken:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def execute(self, _statement): raise SQLAlchemyError("private database")

    monkeypatch.setattr(query, "_session_factory", lambda: Broken())
    with pytest.raises(EosVoucherVerificationError) as error:
        query.verify(tenant_id="tenant-a", voucher_id=VOUCHER_ID, business_operation_id=OPERATION_ID)
    assert error.value.retryable is True
    assert "private database" not in error.value.detail


def test_stable_state_rejects_bad_date_and_committed_time():
    voucher = {
        "voucher_id": VOUCHER_ID, "project_id": PROJECT_ID, "voucher_type": "GENERAL",
        "currency": "KRW", "transaction_date": "bad", "description": "x",
        "requester_ref_type": "oa.user", "requester_id": "u", "source_ref_type": "nsl.request",
        "source_id": "a", "state": "DRAFT", "version": 1,
    }
    with pytest.raises(EosVoucherVerificationError):
        module._stable_state(voucher, [], [])  # noqa: SLF001
    with pytest.raises(EosVoucherVerificationError):
        module._wire_time(None)  # noqa: SLF001
    assert module._wire_time(NOW) == "2026-10-21T01:02:03Z"  # noqa: SLF001


def test_protected_verification_route_maps_success_errors_and_unavailable(database):
    _engine, factory = database
    _seed(factory)
    app = create_eos_app(environ={
        "NEX_EOS_SERVICE_ID": "nex-eos", "NEX_PROFILE": "test", "NEX_VERSION": "p8-s21",
        "NEX_BUILD_SHA": "test", "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    })
    app.state.eos_voucher_verification_query = SqlAlchemyEosVoucherVerificationQuery(factory)
    client = TestClient(app)
    path = f"/internal/v1/finance/voucher-drafts/{VOUCHER_ID}/verification"
    params = {"business_operation_id": OPERATION_ID}
    assert client.get(path, params=params, headers={"X-NeX-Tenant-Id": "tenant-a"}).status_code == 401
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {"Authorization": f"Bearer {token.access_token}", "X-NeX-Tenant-Id": "tenant-a"}
    assert client.get(path, params=params, headers=headers).status_code == 200
    params["business_operation_id"] = "bad"
    assert client.get(path, params=params, headers=headers).status_code == 422
    app.state.eos_voucher_verification_query = None
    assert client.get(path, params=params, headers=headers).status_code == 503
