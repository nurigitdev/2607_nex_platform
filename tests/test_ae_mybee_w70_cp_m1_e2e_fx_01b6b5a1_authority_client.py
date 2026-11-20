from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mybee_ax.orchestration import (
    M1PreparationAuthority,
    load_m1_transaction_preparation_registration,
)
from nex_ae_api.m1_preparation_authority_source import (
    HttpM1PreparationAuthoritySource,
    admit_transaction_preparation_authority,
)
from nex_ae_api.m1_product_planning_coordinator import (
    build_m1_product_planning_coordinator_registration,
)
from nex_ae_api.m1_product_preparation_coordinator import (
    M1ProductPreparationCoordinatorError,
)
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
TENANT = "VO00"
SUBJECT = "employee-100"
COMPANY_ID = "72000000-0000-4000-8000-000000000001"
PROJECT_IDS = (
    "72000000-0000-4000-8000-000000000002",
    "72000000-0000-4000-8000-000000000003",
)
ACCOUNT_IDS = (
    "72000000-0000-4000-8000-000000000004",
    "72000000-0000-4000-8000-000000000005",
)
POLICY_IDS = (
    "72000000-0000-4000-8000-000000000006",
    "72000000-0000-4000-8000-000000000007",
)
PERIOD_ID = "72000000-0000-4000-8000-000000000008"
NOW = datetime(2026, 11, 18, 3, 4, 5, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def _registrations():
    preparation = load_m1_transaction_preparation_registration()
    capabilities = load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
            )
        }
    )
    coordinator = build_m1_product_planning_coordinator_registration(
        product_capabilities=capabilities,
        preparation_registration=preparation,
    )
    return preparation, capabilities, coordinator


def _inputs():
    work_intent = json.loads(
        (
            ROOT
            / "contracts/examples/service/ae_work_intent.business_transaction.v1_2.json"
        ).read_text(encoding="utf-8")
    )
    context = {
        "context_id": "72000000-0000-4000-8000-000000000009",
        "context_generation": 1,
        "execution_id": work_intent["execution_id"],
        "identity": {"tenant_id": TENANT, "subject_id": SUBJECT},
    }
    context["context_hash"] = semantic_sha256_hash_ref(context)
    _preparation, capabilities, coordinator = _registrations()
    snapshot = build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id="72000000-0000-4000-8000-000000000010",
        snapshot_version=1,
        created_at=NOW.isoformat().replace("+00:00", "Z"),
        capabilities=tuple(item.capability for item in capabilities.registrations),
    )
    return work_intent, context, snapshot, {
        "execution_id": work_intent["execution_id"]
    }, coordinator


def _source(*, opener=None):
    preparation, _capabilities, coordinator = _registrations()
    values = {
        "eos_base_url": "http://nex-eos:8107",
        "service_token": "signed-service-token",
        "coordinator_registration": coordinator,
        "preparation_registration": preparation,
    }
    if opener is not None:
        values["opener"] = opener
    return HttpM1PreparationAuthoritySource(**values), preparation


def _response(request: dict) -> dict:
    project_codes = request["project_codes"]
    authority = M1PreparationAuthority(
        tenant_id=TENANT,
        requester_subject_id=SUBJECT,
        company_id=COMPANY_ID,
        company_code="NURIVOICE",
        company_selector_kind=request["company_selector"]["kind"],
        company_selector_value=request["company_selector"]["value"],
        company_version=3,
        company_evidence_hash=HASH_A,
        functional_currency="KRW",
        primary_project_id=PROJECT_IDS[0],
        primary_project_code=project_codes[0],
        project_refs=tuple(
            {
                "project_id": PROJECT_IDS[index],
                "project_code": code,
                "project_version": index + 4,
            }
            for index, code in enumerate(project_codes)
        ),
        project_authorizations=tuple(
            {
                "project_code": code,
                "decision_ref": f"sha256:{index + 1:064x}",
                "revision_hash": HASH_A if index == 0 else HASH_B,
                "source_version": index + 10,
            }
            for index, code in enumerate(project_codes)
        ),
        debit_account_id=ACCOUNT_IDS[0],
        debit_semantic_key=request["debit_semantic_key"],
        debit_account_evidence_hash=HASH_A,
        credit_account_id=ACCOUNT_IDS[1],
        credit_semantic_key=request["credit_semantic_key"],
        credit_account_evidence_hash=HASH_B,
        business_approval_policy_id=POLICY_IDS[0],
        business_approval_policy_version=7,
        business_approval_policy_hash=HASH_A,
        accounting_approval_policy_id=POLICY_IDS[1],
        accounting_approval_policy_version=9,
        accounting_approval_policy_hash=HASH_B,
        project_authorization_ref="oa.project-authority-set:receipt",
        project_authorization_revision_hash=HASH_C,
        authority_effective_at=NOW,
    ).projection()
    period = {
        "period_id": PERIOD_ID,
        "fiscal_year": 2026,
        "period_no": 11,
        "state": "OPEN",
        "version": 2,
        "start_date": "2026-11-01",
        "end_date": "2026-11-30",
    }
    period["evidence_hash"] = semantic_sha256_hash_ref(
        {"domain": "EOS-ACCOUNTING-PERIOD-AUTHORITY-V1", **period}
    )
    response = {
        "schema_version": "eos_transaction_preparation_authority_resolution.v1",
        "operation": "FINANCE.TRANSACTION_PREPARATION_AUTHORITY.RESOLVE",
        "request_hash": request["request_hash"],
        "authority": authority,
        "accounting_period": period,
    }
    response["resolution_hash"] = semantic_sha256_hash_ref(
        {
            "domain": "EOS-TRANSACTION-PREPARATION-AUTHORITY-RESOLUTION-V1",
            **response,
        }
    )
    return response


def test_installed_source_builds_release_bound_request_and_admits_authority() -> None:
    source, preparation = _source()
    work_intent, context, snapshot, execution, coordinator = _inputs()
    request = source.build_request(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
    )

    assert request["tenant_id"] == TENANT
    assert request["requester_subject_id"] == SUBJECT
    assert request["project_codes"] == ["VO00D260101", "VO00D260102"]
    assert request["debit_semantic_key"] == preparation.debit_semantic_key
    assert request["coordinator_binding"]["coordinator_registration_hash"] == (
        coordinator.registration_hash
    )
    admitted = admit_transaction_preparation_authority(
        _response(request),
        request=request,
        preparation_registration=preparation,
    )
    assert admitted.company_id == COMPANY_ID
    assert admitted.primary_project_code == "VO00D260101"
    assert tuple(item["project_code"] for item in admitted.project_refs) == (
        "VO00D260101",
        "VO00D260102",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra="drift"),
        lambda value: value.update(request_hash=HASH_A),
        lambda value: value["authority"].update(tenant_id="OTHER"),
        lambda value: value["authority"].update(debit_semantic_key="MB-COA-DRIFT"),
        lambda value: value["accounting_period"].update(state="CLOSING"),
    ],
)
def test_strict_consumer_rejects_identity_field_and_authority_drift(mutation) -> None:
    source, preparation = _source()
    work_intent, context, snapshot, execution, _coordinator = _inputs()
    request = source.build_request(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
    )
    response = _response(request)
    mutation(response)
    if set(response) == {
        "schema_version",
        "operation",
        "request_hash",
        "authority",
        "accounting_period",
        "resolution_hash",
    }:
        response["resolution_hash"] = semantic_sha256_hash_ref(
            {
                "domain": "EOS-TRANSACTION-PREPARATION-AUTHORITY-RESOLUTION-V1",
                **{
                    key: value
                    for key, value in response.items()
                    if key != "resolution_hash"
                },
            }
        )
    with pytest.raises(M1ProductPreparationCoordinatorError) as raised:
        admit_transaction_preparation_authority(
            response,
            request=request,
            preparation_registration=preparation,
        )
    assert raised.value.error_code == "M1_PREPARATION_AUTHORITY_RESPONSE_DRIFT"


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_http_source_sends_service_identity_and_returns_typed_authority() -> None:
    requests = []

    def opener(request, *, timeout):
        requests.append((request, timeout))
        body = json.loads(request.data.decode("utf-8"))
        return _Response(_response(body))

    source, _preparation = _source(opener=opener)
    work_intent, context, snapshot, execution, _coordinator = _inputs()
    authority = source.resolve(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
        checkpoint=None,
    )

    assert authority.requester_subject_id == SUBJECT
    outgoing, timeout = requests[0]
    assert timeout == 15.0
    assert outgoing.get_header("Authorization") == "Bearer signed-service-token"
    assert outgoing.get_header("X-nex-tenant-id") == TENANT
    assert outgoing.get_header("X-nex-subject-id") == SUBJECT


def test_request_builder_rejects_context_and_execution_drift() -> None:
    source, _preparation = _source()
    work_intent, context, snapshot, execution, _coordinator = _inputs()
    changed = copy.deepcopy(context)
    changed["execution_id"] = "different-execution"
    with pytest.raises(M1ProductPreparationCoordinatorError) as raised:
        source.build_request(
            work_intent=work_intent,
            agent_context=changed,
            capability_snapshot=snapshot,
            execution=execution,
        )
    assert raised.value.error_code == "M1_PREPARATION_AUTHORITY_CONFLICT"
