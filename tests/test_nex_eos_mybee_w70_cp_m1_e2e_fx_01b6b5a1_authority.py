from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from nex_eos.approval_policies import ApprovalPolicySelection
from nex_eos.project_authorization import EosProjectAuthorizationEvidence
from nex_eos.transaction_preparation_authority import (
    TRANSACTION_PREPARATION_AUTHORITY_OPERATION,
    TRANSACTION_PREPARATION_AUTHORITY_REQUEST_SCHEMA,
    EosTransactionPreparationAuthorityError,
    EosTransactionPreparationAuthorityService,
)
from nex_eos.transaction_preparation_authority_api import (
    register_transaction_preparation_authority_routes,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "VO00"
SUBJECT = "employee-100"
COMPANY_ID = "71000000-0000-4000-8000-000000000001"
PROJECT_IDS = (
    "71000000-0000-4000-8000-000000000002",
    "71000000-0000-4000-8000-000000000003",
)
PROJECT_CODES = ("VO00D260101", "VO00D260102")
DEBIT_ID = "71000000-0000-4000-8000-000000000004"
CREDIT_ID = "71000000-0000-4000-8000-000000000005"
PERIOD_ID = "71000000-0000-4000-8000-000000000006"
BUSINESS_POLICY_ID = "71000000-0000-4000-8000-000000000007"
ACCOUNTING_POLICY_ID = "71000000-0000-4000-8000-000000000008"
NOW = datetime(2026, 11, 18, 1, 2, 3, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _request(**overrides) -> dict:
    value = {
        "schema_version": TRANSACTION_PREPARATION_AUTHORITY_REQUEST_SCHEMA,
        "tenant_id": TENANT,
        "requester_subject_id": SUBJECT,
        "business_context_hash": HASH_A,
        "company_selector": {"kind": "CODE_OR_NAME", "value": "NURIVOICE"},
        "project_codes": list(PROJECT_CODES),
        "amount": "2450.00",
        "currency": "USD",
        "recognition_date": "2026-11-18",
        "debit_semantic_key": "MB-COA-OTHER-EXPENSE",
        "credit_semantic_key": "MB-COA-ACCOUNTS-PAYABLE-FX",
        "capability_binding": {
            "capability_id": "FINANCE.VOUCHER.APPROVE_AND_POST",
            "capability_version": "1.0.0",
            "capability_registration_hash": HASH_A,
        },
        "coordinator_binding": {
            "coordinator_id": "MYBEE.M1.TRANSACTION_PREPARATION",
            "coordinator_version": "1.1.0",
            "coordinator_registration_hash": HASH_B,
            "preparation_adapter_source_identity": "mybee:m1-preparation:release",
        },
        "correlation_id": "71000000-0000-4000-8000-000000000009",
    }
    value.update(overrides)
    value["request_hash"] = semantic_sha256_hash_ref(
        {
            "domain": "EOS-TRANSACTION-PREPARATION-AUTHORITY-REQUEST-V1",
            **value,
        }
    )
    return value


class _LegalEntities:
    def __init__(self, *, cross_company: bool = False) -> None:
        self.cross_company = cross_company

    def resolve_active_legal_entity(self, **values):
        assert values["tenant_id"] == TENANT
        return {
            "tenant_id": TENANT,
            "company_id": COMPANY_ID,
            "company_code": "NURIVOICE",
            "name": "NuriVoice",
            "functional_currency": "KRW",
            "status": "ACTIVE",
            "effective_from": date(2026, 1, 1),
            "version": 3,
        }

    def get_effective_project_company_binding(self, **values):
        return {
            "company_id": str(uuid.uuid4()) if self.cross_company else COMPANY_ID,
            "project_id": values["project_id"],
        }


class _Projects:
    def get_project_by_code(self, *, project_code, **_values):
        if project_code not in PROJECT_CODES:
            return None
        index = PROJECT_CODES.index(project_code)
        return {
            "project_id": PROJECT_IDS[index],
            "project_code": project_code,
            "status": "ACTIVE",
            "version": index + 4,
        }


class _Accounts:
    def resolve_semantic_account(self, *, semantic_key, **values):
        assert values["currency"] == "USD"
        account_id = DEBIT_ID if semantic_key.endswith("EXPENSE") else CREDIT_ID
        return {
            "account_ref": {"type": "eos.account", "id": account_id},
            "semantic_key": semantic_key,
            "evidence_hash": HASH_A if account_id == DEBIT_ID else HASH_B,
        }


class _Periods:
    def __init__(self, state: str = "OPEN") -> None:
        self.state = state

    def find_period_for_date(self, **_values):
        return {
            "period_id": PERIOD_ID,
            "fiscal_year": 2026,
            "period_no": 11,
            "state": self.state,
            "version": 2,
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
        }


class _Policies:
    def __init__(self) -> None:
        self.selections: list[ApprovalPolicySelection] = []

    def resolve_policy(self, selection):
        self.selections.append(selection)
        accounting = selection.transaction_type == "ACCOUNTING_POSTING"
        return {
            "approval_policy_id": (
                ACCOUNTING_POLICY_ID if accounting else BUSINESS_POLICY_ID
            ),
            "version": 9 if accounting else 7,
            "policy_hash": HASH_B if accounting else HASH_A,
        }


class _Authorizer:
    def __init__(self, *, deny: bool = False) -> None:
        self.calls = []
        self.deny = deny

    def authorize(self, **values):
        self.calls.append(values)
        if self.deny:
            error = RuntimeError("denied")
            error.status_code = 403
            raise error
        index = PROJECT_CODES.index(values["expected_project_code"])
        return EosProjectAuthorizationEvidence(
            decision_ref=f"sha256:{index + 1:064x}",
            project_code=PROJECT_CODES[index],
            project_role="MEMBER",
            project_status="ACTIVE",
            source_version=index + 10,
            projection_event_hash=HASH_A,
            authorization_revision_hash=HASH_A if index == 0 else HASH_B,
            decided_at=NOW.isoformat(),
        )


def _service(**overrides):
    values = {
        "legal_entities": _LegalEntities(),
        "projects": _Projects(),
        "accounts": _Accounts(),
        "periods": _Periods(),
        "approval_policies": _Policies(),
        "project_authorizer": _Authorizer(),
        "clock": lambda: NOW,
    }
    values.update(overrides)
    return EosTransactionPreparationAuthorityService(**values), values


@pytest.mark.parametrize(
    ("tenant", "company", "project_codes", "currency", "recognition_date"),
    [
        (TENANT, "NURIVOICE", PROJECT_CODES, "USD", "2026-11-18"),
        (TENANT, "NuriVoice", PROJECT_CODES[:1], "USD", "2026-11-19"),
    ],
)
def test_authority_resolution_is_bounded_hash_bound_and_read_only(
    tenant, company, project_codes, currency, recognition_date
) -> None:
    service, dependencies = _service()
    request = _request(
        tenant_id=tenant,
        company_selector={"kind": "CODE_OR_NAME", "value": company},
        project_codes=list(project_codes),
        currency=currency,
        recognition_date=recognition_date,
    )

    result = service.resolve(
        tenant_id=tenant,
        requester_subject_id=SUBJECT,
        payload=request,
    )

    authority = result["authority"]
    assert result["operation"] == TRANSACTION_PREPARATION_AUTHORITY_OPERATION
    assert result["request_hash"] == request["request_hash"]
    assert authority["company_code"] == "NURIVOICE"
    assert [item["project_code"] for item in authority["project_refs"]] == list(
        project_codes
    )
    assert authority["debit_semantic_key"] == request["debit_semantic_key"]
    assert authority["credit_semantic_key"] == request["credit_semantic_key"]
    assert authority["business_approval_policy_version"] == 7
    assert authority["accounting_approval_policy_version"] == 9
    assert result["accounting_period"]["state"] == "OPEN"
    assert len(dependencies["project_authorizer"].calls) == len(project_codes)
    assert all(
        selection.risk_level is None
        for selection in dependencies["approval_policies"].selections
    )
    expected = semantic_sha256_hash_ref(
        {
            "domain": "EOS-TRANSACTION-PREPARATION-AUTHORITY-RESOLUTION-V1",
            **{key: value for key, value in result.items() if key != "resolution_hash"},
        }
    )
    assert result["resolution_hash"] == expected


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"legal_entities": _LegalEntities(cross_company=True)}, 409),
        ({"periods": _Periods("CLOSING")}, 409),
        ({"project_authorizer": _Authorizer(deny=True)}, 403),
    ],
)
def test_drift_revocation_and_cross_scope_fail_closed(overrides, status) -> None:
    service, _dependencies = _service(**overrides)
    with pytest.raises(EosTransactionPreparationAuthorityError) as raised:
        service.resolve(
            tenant_id=TENANT,
            requester_subject_id=SUBJECT,
            payload=_request(),
        )
    assert raised.value.status_code == status


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra="drift"),
        lambda value: value.update(tenant_id="OTHER"),
        lambda value: value.update(request_hash=HASH_A),
        lambda value: value.update(business_context_hash="invalid"),
        lambda value: value.update(project_codes=[]),
        lambda value: value.update(debit_semantic_key="bad"),
    ],
)
def test_request_contract_rejects_malformed_and_semantic_drift(mutation) -> None:
    service, _dependencies = _service()
    request = _request()
    mutation(request)
    with pytest.raises(EosTransactionPreparationAuthorityError) as raised:
        service.resolve(
            tenant_id=TENANT,
            requester_subject_id=SUBJECT,
            payload=request,
        )
    assert raised.value.status_code == 422


@pytest.mark.parametrize(("status", "expected"), [(409, 409), (500, 503)])
def test_authoritative_source_errors_are_translated(status, expected) -> None:
    class _RejectingLegalEntities(_LegalEntities):
        def resolve_active_legal_entity(self, **_values):
            error = RuntimeError("source detail must not escape")
            error.status_code = status
            raise error

    service, _dependencies = _service(legal_entities=_RejectingLegalEntities())

    with pytest.raises(EosTransactionPreparationAuthorityError) as raised:
        service.resolve(
            tenant_id=TENANT,
            requester_subject_id=SUBJECT,
            payload=_request(),
        )

    assert raised.value.status_code == expected
    assert "source detail" not in raised.value.detail


def test_api_is_service_protected_no_store_and_maps_domain_errors(monkeypatch) -> None:
    app = FastAPI()
    register_transaction_preparation_authority_routes(app)
    headers = {
        "Authorization": "Bearer signed-service-token",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Subject-Id": SUBJECT,
    }
    with TestClient(app) as client:
        unauthorized = client.post(
            "/internal/v2/finance/transaction-preparation-authority:resolve",
            headers=headers,
            json=_request(),
        )
        assert unauthorized.status_code == 401
        assert unauthorized.headers["cache-control"] == "no-store, max-age=0"

    monkeypatch.setattr(
        "nex_eos.transaction_preparation_authority_api."
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(subject="nex-ae-api"),
    )
    with TestClient(app) as client:
        unavailable = client.post(
            "/internal/v2/finance/transaction-preparation-authority:resolve",
            headers=headers,
            json=_request(),
        )
        assert unavailable.status_code == 503
        assert unavailable.headers["cache-control"] == "no-store, max-age=0"

    app.state.eos_transaction_preparation_authority_service = _service()[0]
    with TestClient(app) as client:
        accepted = client.post(
            "/internal/v2/finance/transaction-preparation-authority:resolve",
            headers=headers,
            json=_request(),
        )
    assert accepted.status_code == 200
    assert accepted.headers["cache-control"] == "no-store, max-age=0"


def test_contract_schemas_and_openapi_freeze_canonical_boundary() -> None:
    root = Path("contracts")
    request_schema = json.loads(
        (root / "schemas/service/nex_eos/transaction_preparation_authority_resolve.v1.schema.json").read_text()
    )
    response_schema = json.loads(
        (root / "schemas/service/nex_eos/transaction_preparation_authority_resolution.v1.schema.json").read_text()
    )
    Draft202012Validator.check_schema(request_schema)
    Draft202012Validator.check_schema(response_schema)
    Draft202012Validator(
        request_schema, format_checker=FormatChecker()
    ).validate(_request())
    result = _service()[0].resolve(
        tenant_id=TENANT,
        requester_subject_id=SUBJECT,
        payload=_request(),
    )
    Draft202012Validator(
        response_schema, format_checker=FormatChecker()
    ).validate(result)
    spec = yaml.safe_load((root / "openapi/nex-eos.openapi.yaml").read_text())
    operation = spec["paths"][
        "/internal/v2/finance/transaction-preparation-authority:resolve"
    ]["post"]
    assert operation["operationId"] == TRANSACTION_PREPARATION_AUTHORITY_OPERATION
    assert operation["x-nex-side-effect-free"] is True
    assert set(operation["responses"]) >= {"200", "401", "403", "404", "409", "422", "503"}
