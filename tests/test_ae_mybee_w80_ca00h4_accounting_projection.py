from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api.approval_facade import (
    ApprovalFacadeError,
    register_approval_facade_routes,
)
from nex_ae_api.approval_projection import build_user_approval_projection
from nex_ae_api.controlled_skill_runtime import (
    ControlledSkillRuntimeError,
    _accounting_document_ref_from_payload,
)
from nex_ae_api.nsl_approval_publication import (
    ApprovalPublicationError,
    _accounting_document_ref,
)
from nex_runtime import issue_mock_user_token


GATE_ID = "84000000-0000-4000-8000-000000000051"
CASE_ID = "84000000-0000-4000-8000-000000000052"
CANDIDATE_ID = "84000000-0000-4000-8000-000000000053"
CANDIDATE_HASH = "sha256:" + "b" * 64


def _detail(*, nsl: bool = False) -> dict[str, Any]:
    accounting_ref = {
        "schema_version": "ae_accounting_candidate_ref.v1",
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 3,
        "candidate_hash": CANDIDATE_HASH,
    }
    gate = {
        "schema_version": "human_gate_view.p8.v1",
        "gate_id": GATE_ID,
        "approval_domain": "NSL_WRITE" if nsl else "BUSINESS_FORMAL",
        "state": "PENDING",
        "title": "전표 승인",
        "summary": json.dumps(
            {"tool_id": "FINANCE.VOUCHER.APPROVE_AND_POST", "accounting_document_ref": accounting_ref},
            separators=(",", ":"),
        ),
        "action_ref": f"/api/v1/approval-gates/{GATE_ID}",
        "approval_provider_type": "NSL" if nsl else "EOS",
        "approval_target_ref": "approval-nsl" if nsl else f"eos.scoped-approval-case:{CASE_ID}",
        "business_operation_id": "operation-ca00h4",
        "expires_at": None,
    }
    if not nsl:
        gate["formal_approval"] = {
            "schema_version": "business_formal_gate_view.p8.v1",
            "current_stage": 1,
            "stage_count": 2,
            "requested_role": "FINANCE_MANAGER",
            "eos_target_ref": gate["approval_target_ref"],
            "org_unit_id": None,
            "project_id": "T001D260001",
            "terminal_state": None,
        }
    return {
        "schema_version": "wc_approval_gate_detail.v1",
        "gate": gate,
        "created_at": "2026-11-27T01:00:00Z",
        "version": 1,
        "decision_options": ["APPROVE", "REJECT"],
    }


def _document() -> dict[str, Any]:
    return {
        "schema_version": "eos_accounting_document_projection.v1",
        "tenant_id": "tenant-ca00h4",
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 3,
        "candidate_hash": CANDIDATE_HASH,
        "company_id": "company-ca00h4",
        "project_code": "T001D260001",
        "approved_document_ref": "eos.approved-document-envelope:envelope-ca00h4",
        "recognition_date": "2026-11-27",
        "currency": "KRW",
        "requester_subject_id": "employee-1001",
        "approval_case_id": CASE_ID,
        "approval_state": "PENDING",
        "lines": [
            {
                "line_no": 1,
                "account_code": "520100",
                "account_name": "외주인건비",
                "description": "외주 인건비",
                "debit": "125000.0000",
                "credit": "0.0000",
                "currency": "KRW",
            },
            {
                "line_no": 2,
                "account_code": "210200",
                "account_name": "미지급금",
                "description": None,
                "debit": "0.0000",
                "credit": "125000.0000",
                "currency": "KRW",
            },
        ],
        "totals": {
            "debit": "125000.0000",
            "credit": "125000.0000",
            "difference": "0.0000",
            "balanced": True,
        },
    }


class Wc:
    def __init__(self, detail):
        self.detail = detail

    def get_gate(self, *_args, **_kwargs):
        return self.detail

    def list_gates(self, **_kwargs):
        raise AssertionError("not used")

    def decide_gate(self, *_args, **_kwargs):
        raise AssertionError("not used")


class Eos:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def get_case_display(self, case_id, **kwargs):
        self.calls.append(("case", case_id, kwargs))
        if self.error:
            raise self.error
        return _document()

    def get_candidate_display(self, candidate_id, **kwargs):
        self.calls.append(("candidate", candidate_id, kwargs))
        if self.error:
            raise self.error
        return {**_document(), "approval_case_id": None, "approval_state": None}


def _client(*, nsl=False, eos=None):
    app = FastAPI()
    source = eos or Eos()
    register_approval_facade_routes(
        app,
        wc_client=Wc(_detail(nsl=nsl)),
        eos_accounting_client=source,
    )
    token = issue_mock_user_token(tenant_id="tenant-ca00h4", user_id="approver")
    return TestClient(app), {"Authorization": f"Bearer {token.access_token}"}, source


def test_business_formal_projection_joins_exact_eos_case() -> None:
    client, headers, eos = _client()
    response = client.get(f"/api/v1/approval-gates/{GATE_ID}/user-projection", headers=headers)

    assert response.status_code == 200
    document = response.json()["accounting_document"]
    assert document["status"] == "AVAILABLE"
    assert document["header"]["project_code"] == "T001D260001"
    assert document["lines"][0]["account_name"] == "외주인건비"
    assert document["totals"]["balanced"] is True
    assert eos.calls[0][0:2] == ("case", CASE_ID)


def test_nsl_projection_uses_hash_bound_candidate_selector() -> None:
    client, headers, eos = _client(nsl=True)
    response = client.get(f"/api/v1/approval-gates/{GATE_ID}/user-projection", headers=headers)

    assert response.status_code == 200
    assert response.json()["accounting_document"]["status"] == "AVAILABLE"
    assert eos.calls[0][0:2] == ("candidate", CANDIDATE_ID)
    assert eos.calls[0][2]["expected_revision"] == 3
    assert eos.calls[0][2]["expected_hash"] == CANDIDATE_HASH


def test_projection_returns_bounded_unavailable_state_without_inference() -> None:
    client, headers, _ = _client(
        eos=Eos(ApprovalFacadeError(409, "ae.accounting_lineage_conflict", "private detail"))
    )
    response = client.get(f"/api/v1/approval-gates/{GATE_ID}/user-projection", headers=headers)

    assert response.status_code == 200
    document = response.json()["accounting_document"]
    assert document == {
        "schema_version": "ae_accounting_document_projection.v1",
        "status": "UNAVAILABLE",
        "diagnostic_code": "ae.accounting_lineage_conflict",
        "header": None,
        "lines": [],
        "totals": None,
        "lineage": None,
    }
    assert "private detail" not in response.text


def test_base_v1_projection_remains_unchanged_without_accounting_reference() -> None:
    detail = _detail(nsl=True)
    detail["gate"]["summary"] = "일반 보호 작업"
    projection = build_user_approval_projection(tenant_id="tenant-ca00h4", detail=detail)
    assert "accounting_document" not in projection


def test_malformed_nsl_reference_is_visible_but_never_sent_to_eos() -> None:
    detail = _detail(nsl=True)
    summary = json.loads(detail["gate"]["summary"])
    summary["accounting_document_ref"]["candidate_revision"] = True
    detail["gate"]["summary"] = json.dumps(summary, separators=(",", ":"))
    eos = Eos()
    app = FastAPI()
    register_approval_facade_routes(
        app,
        wc_client=Wc(detail),
        eos_accounting_client=eos,
    )
    token = issue_mock_user_token(tenant_id="tenant-ca00h4", user_id="approver")

    response = TestClient(app).get(
        f"/api/v1/approval-gates/{GATE_ID}/user-projection",
        headers={"Authorization": f"Bearer {token.access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["accounting_document"]["diagnostic_code"] == (
        "ae.accounting_reference_invalid"
    )
    assert eos.calls == []


def test_nsl_publication_admits_only_complete_hash_bound_candidate_reference() -> None:
    reference = _accounting_document_ref(
        {
            "schema_version": "ae_accounting_candidate_ref.v1",
            "candidate_id": CANDIDATE_ID,
            "candidate_revision": 3,
            "candidate_hash": CANDIDATE_HASH,
        }
    )
    assert reference["candidate_id"] == CANDIDATE_ID
    with pytest.raises(ApprovalPublicationError, match="reference fields"):
        _accounting_document_ref(
            {
                "schema_version": "ae_accounting_candidate_ref.v1",
                "candidate_id": CANDIDATE_ID,
                "candidate_revision": 3,
            }
        )


def test_controlled_skill_extracts_generic_candidate_selector_or_fails_closed() -> None:
    assert _accounting_document_ref_from_payload({}) is None
    assert _accounting_document_ref_from_payload(
        {
            "candidate_id": CANDIDATE_ID,
            "expected_candidate_revision": 3,
            "expected_candidate_hash": CANDIDATE_HASH,
        }
    ) == {
        "schema_version": "ae_accounting_candidate_ref.v1",
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 3,
        "candidate_hash": CANDIDATE_HASH,
    }
    with pytest.raises(ControlledSkillRuntimeError, match="invalid"):
        _accounting_document_ref_from_payload(
            {
                "candidate_id": CANDIDATE_ID,
                "expected_candidate_revision": 3,
            }
        )
