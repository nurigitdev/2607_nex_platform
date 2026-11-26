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
from nex_ae_api.product_planning_runtime import ProductPlanningRuntimeError
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


@dataclass
class FakeReviewAdmission:
    error: ProductPlanningRuntimeError | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def ingest(self, **values):
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        return {"matched": True}


def _headers() -> dict[str, str]:
    token = issue_mock_user_token(tenant_id="VO00", user_id="employee-8101")
    return {"Authorization": f"Bearer {token.access_token}"}


def _client(
    source: FakeEosClient | None = None,
    *,
    review_admission: FakeReviewAdmission | None = None,
) -> tuple[TestClient, FakeEosClient]:
    app = FastAPI()
    client = source or FakeEosClient()
    register_business_voucher_facade_routes(app, eos_client=client)
    if review_admission is not None:
        app.state.ae_product_review_events = review_admission
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


def test_accounting_submit_admits_owner_scoped_product_review_event() -> None:
    review = FakeReviewAdmission()
    client, _source = _client(review_admission=review)

    submitted = client.post(
        "/api/v1/business-voucher-drafts/candidate-1:submit-for-accounting",
        headers=_headers(),
        json={"confirmed": True},
    )

    assert submitted.status_code == 200
    assert review.calls == [
        {
            "tenant_id": "VO00",
            "requester_ref": "employee-8101",
            "authority_kind": "REQUESTER_VOUCHER_REVIEW",
            "authority_ref": "eos.voucher-candidate:candidate-1",
            "receipt": {"schema_version": "test.v1", "items": []},
        }
    ]

    denied = FakeReviewAdmission(
        error=ProductPlanningRuntimeError(
            "ae.product_planning_runtime_conflict",
            "requester differs",
        )
    )
    denied_client, _source = _client(review_admission=denied)
    failed = denied_client.post(
        "/api/v1/business-voucher-drafts/candidate-1:submit-for-accounting",
        headers=_headers(),
        json={"confirmed": True},
    )
    assert failed.status_code == 409
    assert failed.json()["error_code"] == "ae.product_planning_runtime_conflict"


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
