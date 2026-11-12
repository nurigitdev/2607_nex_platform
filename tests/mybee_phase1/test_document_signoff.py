from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
import yaml
from mybee_ax.domain.documents import (
    BUSINESS_PROPOSAL_TEMPLATE_ID,
    BUSINESS_PROPOSAL_TEMPLATE_VERSION,
    BusinessProposalAttachment,
    BusinessProposalContractError,
    BusinessProposalProjectRef,
    build_business_proposal_form,
    calculate_business_proposal_template_digest,
    load_business_proposal_template,
)
from mybee_ax.integrations.nex_business_approval_client import (
    BusinessApprovalConsumerError,
    BusinessApprovalProviderRequest,
    HttpBusinessApprovalProviderTransport,
    NexBusinessApprovalClient,
    build_business_proposal_approval_request,
)

TENANT = "VO00"
COMPANY_ID = "26000000-0000-4000-8000-000000000001"
PROJECT_A = "26000000-0000-4000-8000-000000000002"
PROJECT_B = "26000000-0000-4000-8000-000000000003"
PROJECT_CODE_A = "VO00D260001"
PROJECT_CODE_B = "VO00D260002"
CASE_ID = "26000000-0000-4000-8000-000000000004"
POLICY_ID = "26000000-0000-4000-8000-000000000005"
OPERATION_ID = "26000000-0000-4000-8000-000000000006"
ENVELOPE_ID = "26000000-0000-4000-8000-000000000007"
NOW = datetime(2026, 11, 11, 6, 0, tzinfo=UTC)


def _attachment(sequence: int = 1, **overrides) -> BusinessProposalAttachment:
    values = {
        "object_ref": f"wa.private-object:receipt-{sequence}",
        "file_name": f"receipt-{sequence}.pdf",
        "media_type": "application/pdf",
        "size_bytes": 1024 * sequence,
        "content_hash": "sha256:" + str(sequence) * 64,
    }
    values.update(overrides)
    return BusinessProposalAttachment(**values)


def _proposal(**overrides):
    values = {
        "tenant_id": TENANT,
        "proposal_id": "proposal-2026-0042",
        "revision": 1,
        "company_id": COMPANY_ID,
        "title": "공용 장비 구매 품의",
        "purpose": "개발팀 공용 테스트 장비 구매",
        "business_justification": "프로젝트 A와 B에서 공동 사용합니다.",
        "scope_type": "PROJECT_SET",
        "project_refs": (
            BusinessProposalProjectRef(PROJECT_B, PROJECT_CODE_B),
            BusinessProposalProjectRef(PROJECT_A, PROJECT_CODE_A),
        ),
        "requested_amount": Decimal(1250000),
        "currency": "KRW",
        "requester_subject_id": "employee-1004",
        "valid_from": NOW + timedelta(days=1),
        "valid_until": NOW + timedelta(days=31),
        "attachments": (_attachment(2), _attachment(1)),
    }
    values.update(overrides)
    return build_business_proposal_form(**values)


def _approval_request(proposal=None):
    return build_business_proposal_approval_request(
        proposal or _proposal(),
        business_operation_id=OPERATION_ID,
        idempotency_key="mb2-01-proposal-42-r1",
        case_id=CASE_ID,
        approval_policy_id=POLICY_ID,
        correlation_id="mb2-01-correlation",
        causation_id="mb2-01-causation",
        expires_at=NOW + timedelta(days=7),
    )


def _receipt(request=None):
    request = request or _approval_request()
    case_input = request.payload["case"]
    project_ids = case_input["project_ids"]
    case = {
        "schema_version": "eos_scoped_approval_case.v2",
        "tenant_id": TENANT,
        "case_id": CASE_ID,
        "company_id": case_input["company_id"],
        "purpose": case_input["purpose"],
        "scope_type": case_input["scope_type"],
        "project_set_hash": "sha256:" + "a" * 64,
        "project_ids": project_ids,
        "subject_ref": case_input["subject_ref"],
        "subject_revision": case_input["subject_revision"],
        "subject_hash": case_input["subject_hash"],
        "requester_ref": {"type": "oa.user", "id": "employee-1004"},
        "approval_policy_ref": {
            "id": POLICY_ID,
            "version": 1,
            "hash": "sha256:" + "b" * 64,
        },
        "oa_decision_ref": "oa.authorization:mb2-01",
        "authorization_revision_hash": "sha256:" + "c" * 64,
        "authorization_checked_at": "2026-11-11T06:00:00Z",
        "state": "PENDING",
        "active_stage_order": 1,
        "stage_count": 1,
        "target_role_ref": "TEAM_LEAD",
        "version": 1,
        "case_hash": "sha256:" + "d" * 64,
        "created_business_operation_id": OPERATION_ID,
        "correlation_id": "mb2-01-correlation",
        "causation_id": "mb2-01-causation",
        "expires_at": "2026-11-18T06:00:00Z",
        "created_at": "2026-11-11T06:00:00Z",
        "updated_at": "2026-11-11T06:00:00Z",
        "decided_at": None,
        "project_bindings": [
            {
                "project_id": project_id,
                "company_id": COMPANY_ID,
                "authorization_scope_hash": "sha256:" + "e" * 64,
            }
            for project_id in project_ids
        ],
    }
    return {
        "schema_version": "eos_scoped_approval_request_receipt.v2",
        "created": True,
        "tenant_id": TENANT,
        "business_operation_id": OPERATION_ID,
        "commit_state": "COMMITTED",
        "scoped_approval_case": case,
        "wc_publication": {
            "created": True,
            "work_item": {
                "tenant_id": TENANT,
                "approval_domain": "BUSINESS_FORMAL",
                "approval_provider_type": "EOS",
                "approval_request_id": CASE_ID,
                "business_operation_id": OPERATION_ID,
                "protected_request_ref": case_input["subject_ref"],
            },
        },
    }


def _envelope(proposal=None):
    proposal = proposal or _proposal()
    return {
        "schema_version": "eos_approved_document_envelope.v2",
        "tenant_id": TENANT,
        "envelope_id": ENVELOPE_ID,
        "company_id": COMPANY_ID,
        "approved_document_id": proposal.proposal_id,
        "document_revision": proposal.revision,
        "document_type": proposal.document_type,
        "work_code": proposal.work_code,
        "document_content_hash": proposal.document_content_hash,
        "attachment_manifest_hash": proposal.attachment_manifest_hash,
        "business_approval_proof_id": str(uuid.uuid4()),
        "business_proof_hash": "sha256:" + "f" * 64,
        "approval_policy_id": POLICY_ID,
        "approval_policy_version": 1,
        "approval_policy_hash": "sha256:" + "1" * 64,
        "scope_type": proposal.scope_type,
        "project_set_hash": "sha256:" + "2" * 64,
        "allowed_project_ids": list(proposal.project_ids),
        "allowed_project_codes": list(proposal.project_codes),
        "approved_amount": "1250000.0000",
        "approved_currency": "KRW",
        "remaining_amount": "1250000.0000",
        "tolerance_policy_hash": None,
        "valid_from": "2026-11-12T06:00:00Z",
        "valid_until": "2026-12-12T06:00:00Z",
        "state": "ACTIVE",
        "usable": True,
        "approved_at": "2026-11-11T07:00:00Z",
        "approved_by_principal_ref": {"type": "oa.user", "id": "approver-1"},
        "source_work_item_ref": "wc.approval-work-item:mb2-01",
        "payload_hash": "sha256:" + "3" * 64,
        "created_business_operation_id": OPERATION_ID,
        "created_at": "2026-11-11T07:00:00Z",
    }


class FakeTransport:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.requests: list[BusinessApprovalProviderRequest] = []

    def send(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def test_template_is_immutable_admitted_provider_contract() -> None:
    template = load_business_proposal_template()
    assert template["template_id"] == BUSINESS_PROPOSAL_TEMPLATE_ID
    assert template["template_version"] == BUSINESS_PROPOSAL_TEMPLATE_VERSION
    assert template["provider_contract"] == {
        "approval_operation": "FINANCE.ACCOUNTING_APPROVAL.REQUEST",
        "approval_purpose": "DOCUMENT_SIGNOFF",
        "approved_document_operation": "BUSINESS.DOCUMENT_APPROVED.GET",
        "provider": "nex-eos",
        "workflow_owner": "nex-wc",
    }
    assert template["runtime_boundaries"]["direct_wc_submission"] is False
    assert template["template_digest"] == calculate_business_proposal_template_digest(
        template
    )


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda item: item.pop("status"), "MYBEE_PROPOSAL_TEMPLATE_INVALID"),
        (
            lambda item: item.__setitem__("template_version", "3.0.0"),
            "MYBEE_PROPOSAL_TEMPLATE_INVALID",
        ),
        (
            lambda item: item["required_fields"].pop(),
            "MYBEE_PROPOSAL_TEMPLATE_INVALID",
        ),
        (
            lambda item: item["provider_contract"].__setitem__(
                "workflow_owner", "mybee"
            ),
            "MYBEE_PROPOSAL_TEMPLATE_INVALID",
        ),
        (
            lambda item: item["runtime_boundaries"].__setitem__(
                "direct_wc_submission", True
            ),
            "MYBEE_PROPOSAL_TEMPLATE_INVALID",
        ),
        (
            lambda item: item["attachment_contract"].__setitem__(
                "content_hash_required", False
            ),
            "MYBEE_PROPOSAL_TEMPLATE_INVALID",
        ),
        (
            lambda item: item.__setitem__("template_digest", "sha256:" + "0" * 64),
            "MYBEE_PROPOSAL_TEMPLATE_HASH_MISMATCH",
        ),
    ],
)
def test_template_drift_fails_closed(tmp_path, mutator, code) -> None:
    source = json.loads(
        Path("domains/mybee/templates/d04/business_proposal.v2.json").read_text(
            encoding="utf-8"
        )
    )
    mutator(source)
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(BusinessProposalContractError) as error:
        load_business_proposal_template(path)
    assert error.value.code == code


@pytest.mark.parametrize("raw", ["not-json", "[]"])
def test_template_unreadable_or_non_object_fails_closed(tmp_path, raw) -> None:
    path = tmp_path / "proposal.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(BusinessProposalContractError) as error:
        load_business_proposal_template(path)
    assert error.value.code in {
        "MYBEE_PROPOSAL_TEMPLATE_UNREADABLE",
        "MYBEE_PROPOSAL_TEMPLATE_INVALID",
    }


def test_proposal_normalizes_projects_attachments_and_hashes_deterministically() -> (
    None
):
    proposal = _proposal()
    assert proposal.project_ids == (PROJECT_A, PROJECT_B)
    assert proposal.project_codes == (PROJECT_CODE_A, PROJECT_CODE_B)
    assert tuple(item.object_ref for item in proposal.attachments) == (
        "wa.private-object:receipt-1",
        "wa.private-object:receipt-2",
    )
    assert proposal.document_content_hash.startswith("sha256:")
    assert proposal.attachment_manifest_hash.startswith("sha256:")
    assert proposal.approval_subject_hash.startswith("sha256:")
    assert (
        proposal.subject_ref == "mybee.business-proposal:proposal-2026-0042:revision:1"
    )

    reordered = _proposal(
        project_refs=(
            BusinessProposalProjectRef(PROJECT_A, PROJECT_CODE_A),
            BusinessProposalProjectRef(PROJECT_B, PROJECT_CODE_B),
        ),
        attachments=(_attachment(1), _attachment(2)),
        valid_from=datetime(2026, 11, 12, 15, 0, tzinfo=timezone(timedelta(hours=9))),
        valid_until=datetime(2026, 12, 12, 15, 0, tzinfo=timezone(timedelta(hours=9))),
    )
    assert reordered.document_content_hash == proposal.document_content_hash
    assert reordered.attachment_manifest_hash == proposal.attachment_manifest_hash
    assert reordered.approval_subject_hash == proposal.approval_subject_hash
    changed = _proposal(requested_amount=Decimal("1250000.0001"))
    assert changed.approval_subject_hash != proposal.approval_subject_hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": " bad"},
        {"proposal_id": " bad"},
        {"revision": 0},
        {"company_id": "not-a-uuid"},
        {"title": ""},
        {"purpose": " bad"},
        {"business_justification": "bad\x00text"},
        {"scope_type": "PERSONAL"},
        {"scope_type": "COMPANY"},
        {"scope_type": "PROJECT", "project_refs": ()},
        {
            "scope_type": "PROJECT_SET",
            "project_refs": (BusinessProposalProjectRef(PROJECT_A, PROJECT_CODE_A),),
        },
        {
            "project_refs": (
                BusinessProposalProjectRef(PROJECT_A, PROJECT_CODE_A),
                BusinessProposalProjectRef(PROJECT_A, PROJECT_CODE_B),
            )
        },
        {"project_refs": "not-an-array"},
        {
            "project_refs": (
                BusinessProposalProjectRef(PROJECT_A, "VO00R260001"),
                BusinessProposalProjectRef(PROJECT_B, PROJECT_CODE_B),
            )
        },
        {"requested_amount": Decimal(0)},
        {"requested_amount": Decimal("1.00001")},
        {"requested_amount": object()},
        {"requested_amount": Decimal("1E+1000000")},
        {"currency": "krw"},
        {"requester_subject_id": " bad"},
        {"valid_from": "2026-11-12"},
        {"valid_until": NOW},
        {"attachments": "not-an-array"},
        {"attachments": (object(),)},
        {"attachments": (_attachment(size_bytes=0),)},
        {"attachments": (_attachment(size_bytes="1024"),)},
        {"attachments": (_attachment(content_hash="bad"),)},
        {"attachments": (_attachment(1), _attachment(1))},
    ],
)
def test_invalid_user_form_input_fails_before_provider(overrides) -> None:
    with pytest.raises(BusinessProposalContractError):
        _proposal(**overrides)


def test_provider_request_binds_exact_form_revision_without_direct_wc_call() -> None:
    proposal = _proposal()
    request = _approval_request(proposal)
    assert request.method == "POST"
    assert request.path == "/internal/v2/finance/accounting-approval-cases"
    assert request.operation_id == "FINANCE.ACCOUNTING_APPROVAL.REQUEST"
    assert request.tenant_id == TENANT
    assert request.subject_id == "employee-1004"
    case = request.payload["case"]
    assert case["purpose"] == "DOCUMENT_SIGNOFF"
    assert case["subject_ref"] == proposal.subject_ref
    assert case["subject_revision"] == proposal.revision
    assert case["subject_hash"] == proposal.approval_subject_hash
    assert case["project_ids"] == [PROJECT_A, PROJECT_B]


def test_client_submits_to_eos_admits_wc_receipt_and_reads_bound_envelope() -> None:
    proposal = _proposal()
    transport = FakeTransport(_receipt(), _envelope(proposal))
    client = NexBusinessApprovalClient(transport)
    receipt = client.submit(
        proposal,
        business_operation_id=OPERATION_ID,
        idempotency_key="mb2-01-proposal-42-r1",
        case_id=CASE_ID,
        approval_policy_id=POLICY_ID,
        correlation_id="mb2-01-correlation",
        causation_id="mb2-01-causation",
        expires_at=NOW + timedelta(days=7),
    )
    assert receipt["wc_publication"]["work_item"]["approval_provider_type"] == "EOS"
    envelope = client.get_approved_document(proposal, envelope_id=ENVELOPE_ID)
    assert envelope["business_approval_proof_id"]
    assert envelope["approved_document_id"] == proposal.proposal_id
    assert [request.operation_id for request in transport.requests] == [
        "FINANCE.ACCOUNTING_APPROVAL.REQUEST",
        "BUSINESS.DOCUMENT_APPROVED.GET",
    ]
    assert transport.requests[1].payload is None


def test_client_rejects_receipt_and_envelope_semantic_drift() -> None:
    proposal = _proposal()
    receipt = _receipt()
    receipt["scoped_approval_case"]["subject_hash"] = "sha256:" + "9" * 64
    with pytest.raises(BusinessApprovalConsumerError) as receipt_error:
        NexBusinessApprovalClient(FakeTransport(receipt)).submit(
            proposal,
            business_operation_id=OPERATION_ID,
            idempotency_key="mb2-01-proposal-42-r1",
            case_id=CASE_ID,
            approval_policy_id=POLICY_ID,
            correlation_id="mb2-01-correlation",
            causation_id="mb2-01-causation",
            expires_at=NOW + timedelta(days=7),
        )
    assert receipt_error.value.code == "MYBEE_PROPOSAL_APPROVAL_BINDING_MISMATCH"

    envelope = _envelope(proposal)
    envelope["approved_amount"] = "1250000.0001"
    with pytest.raises(BusinessApprovalConsumerError) as envelope_error:
        NexBusinessApprovalClient(FakeTransport(envelope)).get_approved_document(
            proposal, envelope_id=ENVELOPE_ID
        )
    assert envelope_error.value.code == "MYBEE_PROPOSAL_ENVELOPE_BINDING_MISMATCH"


class Response:
    def __init__(self, value) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.value


def test_http_transport_sends_signed_eos_headers_and_json(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response(b'{"ok": true}')

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_business_approval_client.urlopen", fake_urlopen
    )
    transport = HttpBusinessApprovalProviderTransport(
        eos_base_url="http://nex-eos:8080",
        service_token="service-token",
        timeout_seconds=12,
    )
    request = _approval_request()
    response = transport.send(request)
    assert response == {"ok": True}
    outgoing = captured["request"]
    assert outgoing.full_url == (
        "http://nex-eos:8080/internal/v2/finance/accounting-approval-cases"
    )
    assert outgoing.get_header("Authorization") == "Bearer service-token"
    assert outgoing.get_header("X-nex-tenant-id") == TENANT
    assert json.loads(outgoing.data)["case"]["purpose"] == "DOCUMENT_SIGNOFF"
    assert captured["timeout"] == 12.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"eos_base_url": "not-a-url", "service_token": "token"},
        {"eos_base_url": "http://eos", "service_token": " "},
        {
            "eos_base_url": "http://eos",
            "service_token": "token",
            "timeout_seconds": 0,
        },
    ],
)
def test_http_transport_configuration_fails_closed(kwargs) -> None:
    with pytest.raises(BusinessApprovalConsumerError) as error:
        HttpBusinessApprovalProviderTransport(**kwargs)
    assert error.value.status_code == 422


def test_http_transport_redacts_rejection_unavailability_and_bad_response(
    monkeypatch,
) -> None:
    request = _approval_request()
    transport = HttpBusinessApprovalProviderTransport(
        eos_base_url="http://eos", service_token="token"
    )

    def rejected(*_args, **_kwargs):
        raise HTTPError(
            "http://eos",
            409,
            "conflict",
            {},
            BytesIO(b'{"error_code":"EOS_CASE_CONFLICT","retryable":false}'),
        )

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_business_approval_client.urlopen", rejected
    )
    with pytest.raises(BusinessApprovalConsumerError) as conflict:
        transport.send(request)
    assert conflict.value.code == "EOS_CASE_CONFLICT"
    assert conflict.value.status_code == 409
    assert conflict.value.retryable is False

    def rejected_without_problem(*_args, **_kwargs):
        raise HTTPError(
            "http://eos",
            502,
            "bad gateway",
            {},
            BytesIO(b"not-json"),
        )

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_business_approval_client.urlopen",
        rejected_without_problem,
    )
    with pytest.raises(BusinessApprovalConsumerError) as rejected_without_body:
        transport.send(request)
    assert rejected_without_body.value.code == "EOS_BUSINESS_APPROVAL_REJECTED"
    assert rejected_without_body.value.retryable is True

    def unavailable(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_business_approval_client.urlopen", unavailable
    )
    with pytest.raises(BusinessApprovalConsumerError) as offline:
        transport.send(request)
    assert offline.value.status_code == 503
    assert offline.value.retryable is True

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_business_approval_client.urlopen",
        lambda *_args, **_kwargs: Response(b"not-json"),
    )
    with pytest.raises(BusinessApprovalConsumerError) as malformed:
        transport.send(request)
    assert malformed.value.status_code == 502

    monkeypatch.setattr(
        "mybee_ax.integrations.nex_business_approval_client.urlopen",
        lambda *_args, **_kwargs: Response(b"[]"),
    )
    with pytest.raises(BusinessApprovalConsumerError) as non_object:
        transport.send(request)
    assert non_object.value.status_code == 502


def test_provider_openapi_operations_remain_canonical() -> None:
    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    approval = spec["paths"]["/internal/v2/finance/accounting-approval-cases"]["post"]
    approved = spec["paths"]["/internal/v2/finance/approved-documents/{envelope_id}"][
        "get"
    ]
    assert approval["operationId"] == "FINANCE.ACCOUNTING_APPROVAL.REQUEST"
    assert approval["x-nex-business-scope"] == "finance:journal:request-approval"
    assert approved["operationId"] == "BUSINESS.DOCUMENT_APPROVED.GET"
    assert approved["x-nex-side-effect-free"] is True
