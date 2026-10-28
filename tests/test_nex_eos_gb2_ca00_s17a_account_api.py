from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import nex_eos.account_api as account_api
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from nex_eos.accounts import (
    AccountInput,
    EosAccountError,
    SqlAlchemyEosAccountRepository,
)
from nex_eos.business_transactions import EOS_METADATA
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class _Repository:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def get_account(self, **values):
        self.calls.append(values)
        return self.value

    def get_effective_account_by_code(self, **values):
        self.calls.append(values)
        return self.value


class _FailingRepository:
    def get_account(self, **_values):
        raise EosAccountError(
            "EOS_ACCOUNT_INVALID",
            "account_id must be a UUID",
            status_code=422,
        )


def _client(monkeypatch, repository=None) -> TestClient:
    app = FastAPI()
    app.state.eos_accounts = repository
    monkeypatch.setattr(
        account_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(subject="nex-ae-api"),
    )
    account_api.register_account_routes(app)
    return TestClient(app)


def test_account_route_returns_tenant_scoped_authoritative_record(monkeypatch) -> None:
    repository = _Repository(
        {
            "tenant_id": "VO00",
            "account_id": "83000000-0000-4000-8000-000000000001",
            "account_code": "TRAVEL",
            "name": "Travel Expense",
            "category": "EXPENSE",
            "account_type": "GENERAL",
            "status": "ACTIVE",
            "effective_from": date(2026, 1, 1),
            "effective_until": None,
            "version": 1,
        }
    )
    client = _client(monkeypatch, repository)

    response = client.get(
        "/internal/v1/accounts/83000000-0000-4000-8000-000000000001",
        headers={"X-NeX-Tenant-Id": "VO00"},
    )

    assert response.status_code == 200
    assert response.json()["account_code"] == "TRAVEL"
    assert repository.calls == [
        {
            "tenant_id": "VO00",
            "account_id": "83000000-0000-4000-8000-000000000001",
        }
    ]

    resolved = client.get(
        "/internal/v1/accounts",
        params={"account_code": "TRAVEL", "effective_at": "2026-10-28"},
        headers={"X-NeX-Tenant-Id": "VO00"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["account_id"] == (
        "83000000-0000-4000-8000-000000000001"
    )
    assert repository.calls[-1] == {
        "tenant_id": "VO00",
        "account_code": "TRAVEL",
        "effective_at": date(2026, 10, 28),
    }


def test_account_route_fails_closed_when_store_or_account_is_missing(monkeypatch) -> None:
    unavailable = _client(monkeypatch)
    assert unavailable.get(
        "/internal/v1/accounts/83000000-0000-4000-8000-000000000001",
        headers={"X-NeX-Tenant-Id": "VO00"},
    ).status_code == 503

    missing = _client(monkeypatch, _Repository(None))
    response = missing.get(
        "/internal/v1/accounts/83000000-0000-4000-8000-000000000001",
        headers={"X-NeX-Tenant-Id": "VO00"},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "EOS_ACCOUNT_NOT_FOUND"


def test_account_route_preserves_service_admission_and_repository_errors(
    monkeypatch,
) -> None:
    denied = _client(monkeypatch, _Repository(None))
    monkeypatch.setattr(
        account_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: JSONResponse(
            status_code=401,
            content={"error_code": "SERVICE_TOKEN_REQUIRED"},
        ),
    )
    denied_response = denied.get(
        "/internal/v1/accounts/83000000-0000-4000-8000-000000000001",
        headers={"X-NeX-Tenant-Id": "VO00"},
    )
    assert denied_response.status_code == 401
    assert denied_response.json()["error_code"] == "SERVICE_TOKEN_REQUIRED"

    invalid = _client(monkeypatch, _FailingRepository())
    invalid_response = invalid.get(
        "/internal/v1/accounts/not-a-uuid",
        headers={"X-NeX-Tenant-Id": "VO00"},
    )
    assert invalid_response.status_code == 422
    assert invalid_response.json()["error_code"] == "EOS_ACCOUNT_INVALID"


def test_account_repository_resolves_effective_account_by_code() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    EOS_METADATA.create_all(engine)
    repository = SqlAlchemyEosAccountRepository(sessionmaker(bind=engine))
    repository.create_account(
        AccountInput(
            tenant_id="VO00",
            account_id="83000000-0000-4000-8000-000000000001",
            account_code="TRAVEL",
            name="Travel Expense",
            category="EXPENSE",
            account_type="GENERAL",
            effective_from=date(2026, 1, 1),
        )
    )

    current = repository.get_effective_account_by_code(
        tenant_id="VO00",
        account_code="TRAVEL",
        effective_at=date(2026, 10, 28),
    )
    expired = repository.get_effective_account_by_code(
        tenant_id="VO00",
        account_code="TRAVEL",
        effective_at=date(2025, 12, 31),
    )

    assert current is not None
    assert current["account_id"] == "83000000-0000-4000-8000-000000000001"
    assert expired is None
