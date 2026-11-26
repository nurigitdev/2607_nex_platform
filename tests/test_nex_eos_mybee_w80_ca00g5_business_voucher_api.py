from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos.business_voucher_api import register_business_voucher_routes
from nex_eos.business_voucher_drafts import EosBusinessVoucherDraftError
from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token


@dataclass
class FakeService:
    error: EosBusinessVoucherDraftError | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def _call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error
        return {"schema_version": "test.v1", "operation": name}

    def list_owner(self, **kwargs):
        return self._call("list", **kwargs)

    def get_owner(self, **kwargs):
        return self._call("get", **kwargs)

    def create(self, **kwargs):
        return self._call("create", **kwargs)

    def revise(self, **kwargs):
        return self._call("revise", **kwargs)

    def validate(self, **kwargs):
        return self._call("validate", **kwargs)

    def submit(self, **kwargs):
        return self._call("submit", **kwargs)


def _headers() -> dict[str, str]:
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-eos",
        scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-NeX-Tenant-Id": "VO00",
        "X-NeX-Subject-Id": "employee-8101",
    }


def _client(service: FakeService | None = None) -> tuple[TestClient, FakeService]:
    app = FastAPI()
    source = service or FakeService()
    app.state.eos_business_voucher_drafts = source
    register_business_voucher_routes(app)
    return TestClient(app), source


def test_product_routes_are_owner_scoped_and_expose_explicit_commands() -> None:
    client, service = _client()
    assert client.get(
        "/internal/v2/business-voucher-drafts?states=DRAFT",
        headers=_headers(),
    ).status_code == 200
    assert client.post(
        "/internal/v2/business-voucher-drafts",
        headers=_headers(),
        json={"client_command_id": "command-1"},
    ).status_code == 201
    assert client.get(
        "/internal/v2/business-voucher-drafts/candidate-1",
        headers=_headers(),
    ).status_code == 200
    assert client.patch(
        "/internal/v2/business-voucher-drafts/candidate-1",
        headers=_headers(),
        json={"expected_revision": 1},
    ).status_code == 200
    assert client.post(
        "/internal/v2/business-voucher-drafts/candidate-1:validate",
        headers=_headers(),
        json={},
    ).status_code == 200
    assert client.post(
        "/internal/v2/business-voucher-drafts/candidate-1:submit-for-accounting",
        headers=_headers(),
        json={"confirmed": True},
    ).status_code == 200

    assert [name for name, _kwargs in service.calls] == [
        "list",
        "create",
        "get",
        "revise",
        "validate",
        "submit",
    ]
    assert all(
        kwargs["tenant_id"] == "VO00" and kwargs["subject_id"] == "employee-8101"
        for _name, kwargs in service.calls
    )


def test_product_routes_fail_closed_for_missing_dependency_and_typed_error() -> None:
    app = FastAPI()
    register_business_voucher_routes(app)
    assert TestClient(app).get(
        "/internal/v2/business-voucher-drafts", headers=_headers()
    ).status_code == 503

    client, _service = _client(
        FakeService(
            error=EosBusinessVoucherDraftError(
                "EOS_BUSINESS_VOUCHER_DRAFT_CONFLICT",
                "stale draft",
                status_code=409,
            )
        )
    )
    failed = client.get(
        "/internal/v2/business-voucher-drafts", headers=_headers()
    )
    assert failed.status_code == 409
    assert failed.json()["error_code"] == "EOS_BUSINESS_VOUCHER_DRAFT_CONFLICT"


def test_validate_rejects_naive_as_of() -> None:
    client, service = _client()
    failed = client.post(
        "/internal/v2/business-voucher-drafts/candidate-1:validate",
        headers=_headers(),
        json={"as_of": "2026-11-26T09:00:00"},
    )
    assert failed.status_code == 422
    assert service.calls == []


def test_routes_reject_missing_trust_and_malformed_or_accept_zoned_as_of() -> None:
    client, service = _client()
    headers = _headers()
    headers.pop("Authorization")
    assert client.get(
        "/internal/v2/business-voucher-drafts", headers=headers
    ).status_code == 401
    malformed = client.post(
        "/internal/v2/business-voucher-drafts/candidate-1:validate",
        headers=_headers(),
        json={"as_of": "not-an-instant"},
    )
    assert malformed.status_code == 422
    accepted = client.post(
        "/internal/v2/business-voucher-drafts/candidate-1:validate",
        headers=_headers(),
        json={"as_of": "2026-11-26T09:00:00+09:00"},
    )
    assert accepted.status_code == 200
    assert service.calls[-1][1]["as_of"].isoformat() == "2026-11-26T00:00:00+00:00"
