from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api import business_proposal_facade
from nex_ae_api.business_proposal_facade import (
    BusinessProposalFacadeError,
    HttpEosBusinessProposalClient,
    build_default_eos_business_proposal_client,
    register_business_proposal_facade_routes,
)
from nex_runtime import issue_mock_user_token

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeEosClient:
    status_code: int = 200
    error: BusinessProposalFacadeError | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request(self, method, path, **kwargs):
        self.calls.append({"method": method, "path": path, **kwargs})
        if self.error:
            raise self.error
        return {"schema_version": "test.v1", "items": []}, self.status_code


def _headers() -> dict[str, str]:
    token = issue_mock_user_token(tenant_id="VO00", user_id="employee-8101")
    return {"Authorization": f"Bearer {token.access_token}"}


def _client(source: FakeEosClient | None = None) -> tuple[TestClient, FakeEosClient]:
    app = FastAPI()
    client = source or FakeEosClient()
    register_business_proposal_facade_routes(app, eos_client=client)
    return TestClient(app), client


def test_facade_derives_owner_scope_and_forwards_product_commands() -> None:
    client, source = _client(FakeEosClient(status_code=201))
    response = client.post(
        "/api/v1/business-proposals",
        headers={**_headers(), "X-Request-ID": "request-g3"},
        json={"proposal_id": "proposal-g3"},
    )

    assert response.status_code == 201
    assert source.calls[0]["tenant_id"] == "VO00"
    assert source.calls[0]["subject_id"] == "employee-8101"
    assert source.calls[0]["path"] == "/internal/v2/business-proposals"
    assert source.calls[0]["payload"] == {"proposal_id": "proposal-g3"}
    assert source.calls[0]["request_id"] == "request-g3"


def test_facade_forwards_filters_and_all_three_submission_commands() -> None:
    client, source = _client()
    assert client.get(
        "/api/v1/business-proposals?state=DRAFT&state=REJECTED",
        headers=_headers(),
    ).status_code == 200
    for command in ("preview-approval", "select-approval-line", "submit"):
        assert client.post(
            f"/api/v1/business-proposals/proposal-g3:{command}",
            headers=_headers(),
            json={"effective_at": "2026-11-26T09:00:00Z"},
        ).status_code == 200
    assert source.calls[0]["params"] == [
        ("states", "DRAFT"),
        ("states", "REJECTED"),
    ]
    assert [call["path"].rsplit(":", 1)[-1] for call in source.calls[1:]] == [
        "preview-approval",
        "select-approval-line",
        "submit",
    ]


def test_facade_rejects_unauthenticated_browser_and_maps_eos_failure() -> None:
    client, source = _client(
        FakeEosClient(
            error=BusinessProposalFacadeError(
                409, "BUSINESS_PROPOSAL_STALE", "stale revision"
            )
        )
    )
    assert client.get("/api/v1/business-proposals").status_code == 401
    failed = client.get("/api/v1/business-proposals", headers=_headers())
    assert failed.status_code == 409
    assert failed.json()["error_code"] == "BUSINESS_PROPOSAL_STALE"
    assert len(source.calls) == 1


def test_http_client_uses_signed_service_trust_and_rejects_bad_response(
    monkeypatch,
) -> None:
    token = "service-token-g3"
    observed: dict[str, Any] = {}

    def request(method, url, **kwargs):
        observed.update({"method": method, "url": url, **kwargs})
        return httpx.Response(200, json={"schema_version": "test.v1"})

    monkeypatch.setattr(business_proposal_facade, "resolve_ae_outbound_service_token", lambda *args, **kwargs: token)
    monkeypatch.setattr(business_proposal_facade.httpx, "request", request)
    client = HttpEosBusinessProposalClient(base_url="https://eos.example/")
    body, status = client.request(
        "GET",
        "/internal/v2/business-proposals",
        tenant_id="VO00",
        subject_id="employee-8101",
        request_id="request-g3",
        trace_id="a" * 32,
    )
    assert status == 200
    assert body["schema_version"] == "test.v1"
    assert observed["headers"]["Authorization"] == f"Bearer {token}"
    assert observed["headers"]["X-NeX-Subject-Id"] == "employee-8101"

    monkeypatch.setattr(
        business_proposal_facade.httpx,
        "request",
        lambda *args, **kwargs: httpx.Response(200, text="not-json"),
    )
    with pytest.raises(BusinessProposalFacadeError) as invalid:
        client.request(
            "GET",
            "/internal/v2/business-proposals",
            tenant_id="VO00",
            subject_id="employee-8101",
            request_id="request-g3",
            trace_id="a" * 32,
        )
    assert invalid.value.status_code == 502


def test_default_client_uses_environment(monkeypatch) -> None:
    monkeypatch.setenv("NEX_EOS_BASE_URL", "https://eos.example")
    monkeypatch.setenv("NEX_AE_TO_EOS_SERVICE_TOKEN", "token-g3")
    client = build_default_eos_business_proposal_client()
    assert client.base_url == "https://eos.example"
    assert client.service_token == "token-g3"


def test_facade_openapi_contract_exposes_the_owner_scoped_review_surface() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-ae-api.openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    paths = spec["paths"]
    assert paths["/api/v1/business-proposals"]["get"]["operationId"] == (
        "listAeBusinessProposals"
    )
    assert paths["/api/v1/business-proposals"]["post"]["operationId"] == (
        "createAeBusinessProposal"
    )
    assert paths["/api/v1/business-proposals/{proposal_id}"]["patch"][
        "operationId"
    ] == "reviseAeBusinessProposal"
    assert paths["/api/v1/business-proposals/{proposal_id}:preview-approval"][
        "post"
    ]["operationId"] == "previewAeBusinessProposalApproval"
    assert paths["/api/v1/business-proposals/{proposal_id}:select-approval-line"][
        "post"
    ]["operationId"] == "selectAeBusinessProposalApprovalLine"
    assert paths["/api/v1/business-proposals/{proposal_id}:submit"]["post"][
        "operationId"
    ] == "submitAeBusinessProposal"
