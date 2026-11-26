from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api import business_voucher_facade
from nex_ae_api.business_voucher_facade import (
    BusinessVoucherFacadeError,
    HttpEosBusinessVoucherClient,
    register_business_voucher_facade_routes,
)
from nex_runtime import issue_mock_user_token


@dataclass
class FakeEosClient:
    status_code: int = 200
    error: BusinessVoucherFacadeError | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        if self.error is not None:
            raise self.error
        return {"schema_version": "test.v1", "items": []}, self.status_code


def _headers() -> dict[str, str]:
    token = issue_mock_user_token(tenant_id="VO00", user_id="employee-8101")
    return {"Authorization": f"Bearer {token.access_token}"}


def _client(source: FakeEosClient | None = None) -> tuple[TestClient, FakeEosClient]:
    app = FastAPI()
    client = source or FakeEosClient()
    register_business_voucher_facade_routes(app, eos_client=client)
    return TestClient(app), client


def test_facade_derives_owner_scope_and_forwards_full_review_surface() -> None:
    client, source = _client(FakeEosClient(status_code=201))
    assert client.post(
        "/api/v1/business-voucher-drafts",
        headers=_headers(),
        json={"client_command_id": "command-1"},
    ).status_code == 201
    assert client.get(
        "/api/v1/business-voucher-drafts?state=DRAFT",
        headers=_headers(),
    ).status_code == 201
    assert client.patch(
        "/api/v1/business-voucher-drafts/candidate-1",
        headers=_headers(),
        json={"expected_revision": 1},
    ).status_code == 201
    for command in ("validate", "submit-for-accounting"):
        assert client.post(
            f"/api/v1/business-voucher-drafts/candidate-1:{command}",
            headers=_headers(),
            json={"confirmed": True},
        ).status_code == 201

    assert all(call["tenant_id"] == "VO00" for call in source.calls)
    assert all(call["subject_id"] == "employee-8101" for call in source.calls)
    assert source.calls[1]["params"] == [("states", "DRAFT")]
    assert source.calls[-1]["path"].endswith(":submit-for-accounting")


def test_facade_rejects_unauthenticated_and_maps_eos_failure() -> None:
    client, source = _client(
        FakeEosClient(
            error=BusinessVoucherFacadeError(
                409,
                "EOS_BUSINESS_VOUCHER_DRAFT_CONFLICT",
                "stale draft",
            )
        )
    )
    assert client.get("/api/v1/business-voucher-drafts").status_code == 401
    failed = client.get("/api/v1/business-voucher-drafts", headers=_headers())
    assert failed.status_code == 409
    assert failed.json()["error_code"] == "EOS_BUSINESS_VOUCHER_DRAFT_CONFLICT"
    assert len(source.calls) == 1


def test_http_client_uses_service_trust_and_rejects_invalid_body(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    def request(method, url, **kwargs):
        observed.update({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json={"schema_version": "test.v1"})

    monkeypatch.setattr(
        business_voucher_facade,
        "resolve_ae_outbound_service_token",
        lambda *args, **kwargs: "service-token",
    )
    monkeypatch.setattr(business_voucher_facade.httpx, "request", request)
    client = HttpEosBusinessVoucherClient(base_url="https://eos.example/")
    body, status = client.request(
        "GET",
        "/internal/v2/business-voucher-drafts",
        tenant_id="VO00",
        subject_id="employee-8101",
        request_id="request-g5",
        trace_id="a" * 32,
    )
    assert status == 200
    assert body["schema_version"] == "test.v1"
    assert observed["headers"]["X-NeX-Subject-Id"] == "employee-8101"

    monkeypatch.setattr(
        business_voucher_facade.httpx,
        "request",
        lambda *args, **kwargs: httpx.Response(200, text="not-json"),
    )
    with pytest.raises(BusinessVoucherFacadeError) as invalid:
        client.request(
            "GET",
            "/internal/v2/business-voucher-drafts",
            tenant_id="VO00",
            subject_id="employee-8101",
            request_id="request-g5",
            trace_id="a" * 32,
        )
    assert invalid.value.status_code == 502
