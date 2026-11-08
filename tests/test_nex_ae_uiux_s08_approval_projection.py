from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from nex_ae_api.approval_facade import (
    ApprovalFacadeError,
    register_approval_facade_routes,
)
from nex_ae_api.approval_projection import (
    ApprovalProjectionError,
    build_user_approval_projection,
)
from nex_runtime import issue_mock_user_token


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "contracts/schemas/service/nex_ae_api/user_approval_projection.v1.schema.json"
)
GATE_ID = "82000000-0000-4000-8000-000000000008"


def _gate(*, formal: bool = False, summary: str = "전표 등록 요청을 검토합니다."):
    gate: dict[str, Any] = {
        "schema_version": "human_gate_view.p8.v1",
        "gate_id": GATE_ID,
        "approval_domain": "BUSINESS_FORMAL" if formal else "NSL_WRITE",
        "state": "PENDING",
        "title": "승인 요청",
        "summary": summary,
        "action_ref": f"/api/v1/approval-gates/{GATE_ID}",
        "approval_provider_type": "EOS" if formal else "NSL",
        "approval_target_ref": "eos-stage-s08" if formal else "nsl-request-s08",
        "business_operation_id": "operation-s08" if formal else None,
        "expires_at": "2026-11-09T09:00:00Z",
    }
    if formal:
        gate["formal_approval"] = {
            "schema_version": "business_formal_gate_view.p8.v1",
            "current_stage": 1,
            "stage_count": 2,
            "requested_role": "TEAM_LEAD",
            "eos_target_ref": "eos-stage-s08",
            "org_unit_id": "org-finance",
            "project_id": "project-nvt",
            "terminal_state": None,
        }
    return gate


def _detail(*, formal: bool = False, summary: str = "전표 등록 요청을 검토합니다."):
    return {
        "schema_version": "wc_approval_gate_detail.v1",
        "gate": _gate(formal=formal, summary=summary),
        "created_at": "2026-11-08T08:00:00Z",
        "version": 1,
        "decision_options": ["APPROVE", "REJECT"],
    }


class FakeWcApprovalClient:
    def __init__(
        self,
        detail: dict[str, Any] | None = None,
        error: ApprovalFacadeError | None = None,
    ):
        self.detail = detail or _detail(formal=True)
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def get_gate(self, approval_work_item_id: str, **kwargs):
        self.calls.append({"approval_work_item_id": approval_work_item_id, **kwargs})
        if self.error is not None:
            raise self.error
        return self.detail

    def list_gates(self, **kwargs):  # pragma: no cover - route protocol only
        raise AssertionError("not used")

    def decide_gate(self, *args, **kwargs):  # pragma: no cover - route protocol only
        raise AssertionError("not used")


def _headers(*, tenant_id: str = "tenant-s08") -> dict[str, str]:
    token = issue_mock_user_token(tenant_id=tenant_id, user_id="approver-s08")
    return {"Authorization": f"Bearer {token.access_token}"}


def _client(source: FakeWcApprovalClient) -> TestClient:
    app = FastAPI()
    register_approval_facade_routes(app, wc_client=source)
    return TestClient(app)


def _validate_schema(value: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def test_projection_is_schema_valid_and_keeps_absent_authority_open() -> None:
    detail = _detail()
    detail["gate"] = {**detail["gate"], "expires_at": None}
    projection = build_user_approval_projection(
        tenant_id="tenant-s08",
        detail=detail,
    )

    _validate_schema(projection)
    assert projection["requested_at"] == {
        "status": "AVAILABLE",
        "value": "2026-11-08T08:00:00Z",
    }
    assert projection["requester"] == {"status": "OPEN", "display_name": None}
    assert projection["project"]["id_status"] == "OPEN"
    assert projection["amount"] == {
        "status": "OPEN",
        "value": None,
        "currency": None,
    }
    assert projection["accounts"] == {"status": "OPEN", "items": []}
    assert projection["expires_at"] is None
    assert projection["metadata"]["browser_join_required"] is False


def test_projection_admits_only_the_existing_formal_project_identity() -> None:
    projection = build_user_approval_projection(
        tenant_id="tenant-s08",
        detail=_detail(formal=True),
    )

    _validate_schema(projection)
    assert projection["project"] == {
        "id_status": "AVAILABLE",
        "project_id": "project-nvt",
        "display_status": "OPEN",
        "display_name": None,
    }
    assert projection["amount"]["status"] == "OPEN"
    assert projection["risk"]["status"] == "OPEN"
    assert projection["line_items"]["items"] == []


def test_schema_admits_only_explicit_authoritative_business_values() -> None:
    projection = build_user_approval_projection(
        tenant_id="tenant-s08",
        detail=_detail(formal=True),
    )
    projection.update(
        requester={"status": "AVAILABLE", "display_name": "김승인"},
        project={
            **projection["project"],
            "display_status": "AVAILABLE",
            "display_name": "NVT 프로젝트",
        },
        amount={"status": "AVAILABLE", "value": "125000.00", "currency": "KRW"},
        business_date={"status": "AVAILABLE", "value": "2026-11-08"},
        accounts={
            "status": "AVAILABLE",
            "items": [{"code": "8110", "display_name": "여비교통비"}],
        },
        risk={
            "status": "AVAILABLE",
            "level": "LOW",
            "explanation": "예산 범위 내",
        },
        line_items={
            "status": "AVAILABLE",
            "items": [
                {
                    "line_no": 1,
                    "description": "출장 교통비",
                    "account_code": "8110",
                    "amount": "125000.00",
                    "currency": "KRW",
                }
            ],
        },
    )

    _validate_schema(projection)
    projection["amount"] = {
        "status": "OPEN",
        "value": "125000.00",
        "currency": "KRW",
    }
    with pytest.raises(ValidationError):
        _validate_schema(projection)


@pytest.mark.parametrize(
    "detail",
    (
        {**_detail(), "schema_version": "old"},
        {**_detail(), "gate": None},
        {**_detail(), "created_at": None},
        {**_detail(), "created_at": "2026-11-08T08:00:00"},
        {**_detail(), "created_at": "not-a-date"},
        _detail(summary='{"service_token":"private"}'),
        {**_detail(), "gate": {**_gate(), "approval_domain": "UNKNOWN"}},
        {**_detail(), "gate": {**_gate(), "state": "UNKNOWN"}},
        {**_detail(), "gate": {**_gate(), "gate_id": "not-a-uuid"}},
        {**_detail(), "gate": {**_gate(), "gate_id": "{" + GATE_ID + "}"}},
        {**_detail(), "gate": {**_gate(), "expires_at": "not-a-date"}},
        {
            **_detail(formal=True),
            "gate": {
                key: value
                for key, value in _gate(formal=True).items()
                if key != "formal_approval"
            },
        },
    ),
)
def test_projection_fails_closed_on_invalid_or_protected_source(detail) -> None:
    with pytest.raises(ApprovalProjectionError):
        build_user_approval_projection(tenant_id="tenant-s08", detail=detail)


def test_projection_route_preserves_browser_tenant_and_wc_authorization() -> None:
    source = FakeWcApprovalClient()
    response = _client(source).get(
        f"/api/v1/approval-gates/{GATE_ID}/user-projection",
        headers=_headers(tenant_id="tenant-owner-s08"),
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-owner-s08"
    assert response.json()["requester"]["status"] == "OPEN"
    assert source.calls[0]["tenant_id"] == "tenant-owner-s08"
    assert source.calls[0]["subject_id"] == "approver-s08"


def test_projection_route_requires_session_and_maps_unsafe_source() -> None:
    source = FakeWcApprovalClient(_detail(summary='{"password":"private"}'))
    client = _client(source)

    missing = client.get(f"/api/v1/approval-gates/{GATE_ID}/user-projection")
    unsafe = client.get(
        f"/api/v1/approval-gates/{GATE_ID}/user-projection",
        headers=_headers(),
    )

    assert missing.status_code == 401
    assert unsafe.status_code == 502
    assert unsafe.json()["error_code"] == "ae.approval_projection_invalid"
    assert "private" not in unsafe.text


def test_projection_route_preserves_wc_authorization_failure() -> None:
    source = FakeWcApprovalClient(
        error=ApprovalFacadeError(
            403,
            "wc.approval_authorization_denied",
            "Current approval read authority was denied.",
        )
    )

    response = _client(source).get(
        f"/api/v1/approval-gates/{GATE_ID}/user-projection",
        headers=_headers(),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "wc.approval_authorization_denied"
