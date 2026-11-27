from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos.accounting_display import (
    EosAccountingDisplayError,
    EosAccountingDisplayService,
)
from nex_eos.accounting_display_api import register_accounting_display_routes
from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token


TENANT = "tenant-ca00h4"
CASE_ID = "84000000-0000-4000-8000-000000000041"
CANDIDATE_ID = "84000000-0000-4000-8000-000000000042"
COMPANY_ID = "84000000-0000-4000-8000-000000000043"
PROJECT_ID = "84000000-0000-4000-8000-000000000044"
ENVELOPE_ID = "84000000-0000-4000-8000-000000000045"
DEBIT_ID = "84000000-0000-4000-8000-000000000046"
CREDIT_ID = "84000000-0000-4000-8000-000000000047"
CANDIDATE_HASH = "sha256:" + "a" * 64


class Cases:
    def __init__(self, value=None):
        self.value = value or {
            "purpose": "ACCOUNTING_POSTING",
            "subject_ref": f"eos.voucher-candidate:{CANDIDATE_ID}",
            "subject_revision": 2,
            "subject_hash": CANDIDATE_HASH,
            "state": "PENDING",
            "requester_ref": {"type": "oa.user", "id": "employee-1001"},
        }

    def get_case(self, **_kwargs):
        return self.value


class Reviews:
    def __init__(self, value=None):
        self.value = value or {
            "candidate_id": CANDIDATE_ID,
            "candidate_revision": 2,
            "candidate_hash": CANDIDATE_HASH,
        }

    def get(self, **_kwargs):
        return self.value


class Candidates:
    def __init__(self, value=None):
        self.value = value or {
            "candidate_id": CANDIDATE_ID,
            "company_id": COMPANY_ID,
            "project_id": PROJECT_ID,
            "project_code": "T001D260001",
            "document_envelope_id": ENVELOPE_ID,
            "preparer_subject_id": "employee-1001",
            "transaction_currency": "KRW",
            "recognition_date": date(2026, 11, 27),
            "current_revision_no": 2,
            "revision": {
                "revision_no": 2,
                "candidate_hash": CANDIDATE_HASH,
            },
            "lines": [
                {
                    "line_no": 1,
                    "account_id": DEBIT_ID,
                    "description": "외주 인건비",
                    "debit_original": Decimal("125000.0000"),
                    "credit_original": Decimal("0"),
                },
                {
                    "line_no": 2,
                    "account_id": CREDIT_ID,
                    "description": "미지급금",
                    "debit_original": Decimal("0"),
                    "credit_original": Decimal("125000.0000"),
                },
            ],
        }

    def get(self, **_kwargs):
        return self.value


class Accounts:
    values = {
        DEBIT_ID: {"account_code": "520100", "name": "외주인건비"},
        CREDIT_ID: {"account_code": "210200", "name": "미지급금"},
    }

    def get_account(self, *, account_id, **_kwargs):
        return self.values.get(account_id)


def _service(**overrides):
    return EosAccountingDisplayService(
        scoped_approvals=overrides.get("cases", Cases()),
        accounting_reviews=overrides.get("reviews", Reviews()),
        candidates=overrides.get("candidates", Candidates()),
        accounts=overrides.get("accounts", Accounts()),
    )


def _api_client(*, service=True):
    app = FastAPI()
    if service:
        app.state.eos_accounting_display_service = _service()
    register_accounting_display_routes(app)
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-eos",
        scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    return TestClient(app), {
        "Authorization": f"Bearer {issued.access_token}",
        "X-NeX-Tenant-Id": TENANT,
    }


def test_case_projection_uses_exact_candidate_revision_and_account_names() -> None:
    result = _service().project_case(tenant_id=TENANT, case_id=CASE_ID)

    assert result["schema_version"] == "eos_accounting_document_projection.v1"
    assert result["candidate_revision"] == 2
    assert result["project_code"] == "T001D260001"
    assert result["lines"][0] == {
        "line_no": 1,
        "account_code": "520100",
        "account_name": "외주인건비",
        "description": "외주 인건비",
        "debit": "125000.0000",
        "credit": "0.0000",
        "currency": "KRW",
    }
    assert result["totals"] == {
        "debit": "125000.0000",
        "credit": "125000.0000",
        "difference": "0.0000",
        "balanced": True,
    }


def test_direct_projection_supports_hash_bound_nsl_write_selector() -> None:
    result = _service().project_candidate(
        tenant_id=TENANT,
        candidate_id=CANDIDATE_ID,
        expected_revision=2,
        expected_hash=CANDIDATE_HASH,
    )

    assert result["approval_case_id"] is None
    assert result["requester_subject_id"] == "employee-1001"


@pytest.mark.parametrize(
    ("overrides", "match"),
    (
        ({"cases": Cases({**Cases().value, "purpose": "DOCUMENT_SIGNOFF"})}, "not an accounting"),
        ({"reviews": Reviews({**Reviews().value, "candidate_revision": 1})}, "lineage differ"),
        ({"candidates": Candidates({**Candidates().value, "current_revision_no": 3})}, "revision differs"),
        ({"accounts": type("MissingAccounts", (), {"get_account": lambda *_a, **_k: None})()}, "account identity"),
    ),
)
def test_projection_fails_closed_for_ambiguous_or_stale_lineage(overrides, match) -> None:
    with pytest.raises(EosAccountingDisplayError, match=match):
        _service(**overrides).project_case(tenant_id=TENANT, case_id=CASE_ID)


def test_projection_rejects_invalid_selector_without_repository_access() -> None:
    with pytest.raises(EosAccountingDisplayError, match="expected_revision"):
        _service().project_candidate(
            tenant_id=TENANT,
            candidate_id=CANDIDATE_ID,
            expected_revision=True,
            expected_hash=CANDIDATE_HASH,
        )


def test_protected_api_projects_case_and_hash_bound_candidate() -> None:
    client, headers = _api_client()

    case_response = client.get(
        f"/internal/v2/finance/accounting-approval-cases/{CASE_ID}/display",
        headers=headers,
    )
    candidate_response = client.get(
        f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/accounting-display",
        params={"expected_revision": 2, "expected_hash": CANDIDATE_HASH},
        headers=headers,
    )

    assert case_response.status_code == 200
    assert case_response.json()["approval_case_id"] == CASE_ID
    assert candidate_response.status_code == 200
    assert candidate_response.json()["candidate_hash"] == CANDIDATE_HASH


def test_protected_api_rejects_missing_trust_and_missing_dependencies() -> None:
    client, headers = _api_client(service=False)

    denied = client.get(
        f"/internal/v2/finance/accounting-approval-cases/{CASE_ID}/display",
        headers={"X-NeX-Tenant-Id": TENANT},
    )
    unavailable = client.get(
        f"/internal/v2/finance/accounting-approval-cases/{CASE_ID}/display",
        headers=headers,
    )

    assert denied.status_code == 401
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "EOS_ACCOUNTING_DISPLAY_UNAVAILABLE"


def test_protected_api_preserves_typed_display_error() -> None:
    client, headers = _api_client()

    response = client.get(
        "/internal/v2/finance/accounting-approval-cases/not-a-uuid/display",
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "EOS_ACCOUNTING_DISPLAY_INVALID"
