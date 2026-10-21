from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_METADATA,
    EosBusinessQueryError,
    SqlAlchemyEosBusinessOperationQuery,
    create_eos_app,
)
from nex_eos import business_queries as query_module
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

OPERATION_ID = "86000000-0000-4000-8000-000000000001"
VOUCHER_ID = "84000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 21, 1, 2, 3, tzinfo=UTC)


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _insert(factory, *, tenant="tenant-a", state="COMMITTED", result=None, committed_at=NOW):
    if result is None and state == "COMMITTED":
        result = {"voucher_id": VOUCHER_ID}
    with factory.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=tenant,
                business_operation_id=OPERATION_ID,
                idempotency_key="query-1",
                operation="FINANCE.CREATE_VOUCHER_DRAFT",
                payload_hash="sha256:" + "a" * 64,
                commit_state=state,
                result_json=result,
                created_at=NOW,
                committed_at=committed_at,
            )
        )


def test_committed_query_returns_stable_business_and_voucher_refs(factory):
    _insert(factory)
    result = SqlAlchemyEosBusinessOperationQuery(factory).get(
        tenant_id="tenant-a", business_operation_id=OPERATION_ID
    )
    assert result["commit_state"] == "COMMITTED"
    assert result["reconciliation_status"] == "COMMITTED_CONFIRMED"
    assert result["voucher_ref"] == {"type": "eos.voucher_draft", "id": VOUCHER_ID}
    assert result["last_observed_at"] == "2026-10-21T01:02:03Z"


@pytest.mark.parametrize(
    "state,expected_state,reconciliation",
    (
        ("NOT_COMMITTED", "NOT_COMMITTED", "NOT_COMMITTED_CONFIRMED"),
        ("PENDING", "UNKNOWN_COMMIT_STATE", "RECONCILIATION_REQUIRED"),
    ),
)
def test_not_committed_and_pending_are_distinct(factory, state, expected_state, reconciliation):
    _insert(factory, state=state, result={}, committed_at=None)
    result = SqlAlchemyEosBusinessOperationQuery(factory).get(
        tenant_id="tenant-a", business_operation_id=OPERATION_ID
    )
    assert result["commit_state"] == expected_state
    assert result["reconciliation_status"] == reconciliation
    assert result["voucher_ref"] is None


def test_unknown_and_cross_tenant_are_same_not_found_boundary(factory):
    query = SqlAlchemyEosBusinessOperationQuery(factory)
    with pytest.raises(EosBusinessQueryError) as unknown:
        query.get(tenant_id="tenant-a", business_operation_id=OPERATION_ID)
    assert unknown.value.status_code == 404
    _insert(factory)
    with pytest.raises(EosBusinessQueryError) as cross_tenant:
        query.get(tenant_id="tenant-b", business_operation_id=OPERATION_ID)
    assert cross_tenant.value.error_code == unknown.value.error_code


@pytest.mark.parametrize("state,result", (("COMMITTED", {}), ("CORRUPT", {})))
def test_incomplete_or_unknown_stored_state_fails_closed(factory, state, result):
    _insert(factory, state=state, result=result)
    with pytest.raises(EosBusinessQueryError) as error:
        SqlAlchemyEosBusinessOperationQuery(factory).get(
            tenant_id="tenant-a", business_operation_id=OPERATION_ID
        )
    assert error.value.error_code == "EOS_BUSINESS_OPERATION_STATE_INVALID"
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "tenant,operation_id",
    (("bad value", OPERATION_ID), ("tenant-a", "bad")),
)
def test_query_identity_validation(factory, tenant, operation_id):
    with pytest.raises(EosBusinessQueryError) as error:
        SqlAlchemyEosBusinessOperationQuery(factory).get(
            tenant_id=tenant, business_operation_id=operation_id
        )
    assert error.value.status_code == 422


def test_query_database_failure_is_retryable_and_redacted(factory, monkeypatch):
    query = SqlAlchemyEosBusinessOperationQuery(factory)

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private database url")

    monkeypatch.setattr(query, "_session_factory", lambda: BrokenSession())
    with pytest.raises(EosBusinessQueryError) as error:
        query.get(tenant_id="tenant-a", business_operation_id=OPERATION_ID)
    assert error.value.status_code == 503
    assert error.value.retryable is True
    assert "private database" not in error.value.detail


def test_query_rejects_missing_observation_time(factory):
    with pytest.raises(EosBusinessQueryError):
        query_module._wire_time(None)  # noqa: SLF001
    assert query_module._wire_time(NOW) == "2026-10-21T01:02:03Z"  # noqa: SLF001


def test_protected_query_route_maps_success_not_found_and_unavailable(factory):
    _insert(factory)
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s20",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_business_operation_query = SqlAlchemyEosBusinessOperationQuery(factory)
    client = TestClient(app)
    path = f"/internal/v1/business-operations/{OPERATION_ID}"
    assert client.get(path, headers={"X-NeX-Tenant-Id": "tenant-a"}).status_code == 401
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": "tenant-a",
    }
    assert client.get(path, headers=headers).status_code == 200
    headers["X-NeX-Tenant-Id"] = "tenant-b"
    assert client.get(path, headers=headers).status_code == 404
    app.state.eos_business_operation_query = None
    assert client.get(path, headers=headers).status_code == 503
