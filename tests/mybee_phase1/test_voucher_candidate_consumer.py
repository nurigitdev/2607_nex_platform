from __future__ import annotations

import copy
import inspect
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
import yaml
from mybee_ax.integrations import nex_voucher_candidate_client as consumer_module
from mybee_ax.integrations.nex_voucher_candidate_client import (
    CREATE_OPERATION,
    REVIEW_GET_OPERATION,
    VALIDATE_OPERATION,
    HttpVoucherCandidateProviderTransport,
    NexVoucherCandidateClient,
    VoucherCandidateConsumerError,
    VoucherCandidateLine,
    VoucherCandidateProviderRequest,
    admit_candidate_create_result,
    admit_candidate_review_projection,
    admit_candidate_validation_result,
    build_candidate_create_request,
    build_candidate_review_request,
    build_candidate_validation_request,
    build_voucher_candidate_draft,
)
from nex_eos.voucher_candidate_commands import (
    parse_create_voucher_candidate_command,
    voucher_candidate_payload_hash,
)

TENANT = "VO00"
COMPANY_ID = "26000000-0000-4000-8000-000000000001"
PROJECT_ID = "26000000-0000-4000-8000-000000000002"
PROJECT_CODE = "VO00D260001"
ENVELOPE_ID = "26000000-0000-4000-8000-000000000003"
CREATE_OPERATION_ID = "26000000-0000-4000-8000-000000000004"
REVIEW_OPERATION_ID = "26000000-0000-4000-8000-000000000005"
CASE_ID = "26000000-0000-4000-8000-000000000006"
POLICY_ID = "26000000-0000-4000-8000-000000000007"
CANDIDATE_ID = "26000000-0000-4000-8000-000000000008"
REVISION_ID = "26000000-0000-4000-8000-000000000009"
OUTBOX_ID = "26000000-0000-4000-8000-000000000010"
PERIOD_ID = "26000000-0000-4000-8000-000000000011"
DEBIT_ACCOUNT_ID = "26000000-0000-4000-8000-000000000012"
CREDIT_ACCOUNT_ID = "26000000-0000-4000-8000-000000000013"
EVENT_ID = "26000000-0000-4000-8000-000000000014"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64
NOW = datetime(2026, 11, 12, 3, 0, tzinfo=UTC)


def _document(**overrides):
    value = {
        "schema_version": "eos_approved_document_envelope.v2",
        "tenant_id": TENANT,
        "envelope_id": ENVELOPE_ID,
        "company_id": COMPANY_ID,
        "approved_document_id": "proposal-2026-0042",
        "document_revision": 1,
        "document_type": "BUSINESS_PROPOSAL",
        "work_code": "FL0004011",
        "document_content_hash": HASH_A,
        "attachment_manifest_hash": HASH_B,
        "business_approval_proof_id": str(uuid.uuid4()),
        "business_proof_hash": HASH_C,
        "approval_policy_id": POLICY_ID,
        "approval_policy_version": 1,
        "approval_policy_hash": HASH_D,
        "scope_type": "PROJECT",
        "project_set_hash": HASH_E,
        "allowed_project_ids": [PROJECT_ID],
        "allowed_project_codes": [PROJECT_CODE],
        "approved_amount": "10000.0000",
        "approved_currency": "KRW",
        "remaining_amount": "10000.0000",
        "tolerance_policy_hash": None,
        "valid_from": "2026-11-01T00:00:00Z",
        "valid_until": "2026-12-31T00:00:00Z",
        "state": "ACTIVE",
        "usable": True,
        "approved_at": "2026-11-11T03:00:00Z",
        "approved_by_principal_ref": {"type": "oa.user", "id": "approver-1"},
        "source_work_item_ref": "wc.approval-work-item:proposal-2026-0042",
        "payload_hash": HASH_A,
        "created_business_operation_id": CREATE_OPERATION_ID,
        "created_at": "2026-11-11T03:00:00Z",
    }
    value.update(overrides)
    return value


def _lines():
    return (
        VoucherCandidateLine(
            account_id=DEBIT_ACCOUNT_ID,
            debit_original=Decimal(10000),
            credit_original=Decimal(0),
            source_record_line_ref="expense-line-1",
            description="Travel expense",
            evidence_hash=HASH_A,
        ),
        VoucherCandidateLine(
            account_id=CREDIT_ACCOUNT_ID,
            debit_original=Decimal(0),
            credit_original=Decimal(10000),
            source_record_line_ref="expense-line-2",
            description=None,
            evidence_hash=HASH_B,
        ),
    )


def _draft(**overrides):
    values = {
        "tenant_id": TENANT,
        "company_id": COMPANY_ID,
        "preparer_subject_id": "employee-1004",
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "approved_document": _document(),
        "source_kind": "EXPENSE_CLAIM",
        "source_record_ref": "mybee.expense:travel-2026-0042",
        "business_work_code": "FL0004011",
        "transaction_currency": "KRW",
        "recognition_date": date(2026, 11, 12),
        "lines": _lines(),
    }
    values.update(overrides)
    return build_voucher_candidate_draft(**values)


def _create_request(draft=None):
    return build_candidate_create_request(
        draft or _draft(),
        business_operation_id=CREATE_OPERATION_ID,
        idempotency_key="mb3-01-candidate-42",
        trace_id="trace-mb3-01",
        correlation_id="correlation-mb3-01",
        causation_id="causation-mb3-01",
    )


def _create_result(request=None, **overrides):
    request = request or _create_request()
    value = {
        "schema_version": "eos_voucher_candidate_create_result.v2",
        "tenant_id": TENANT,
        "business_operation_id": CREATE_OPERATION_ID,
        "idempotency_key": "mb3-01-candidate-42",
        "payload_hash": request.payload["payload_hash"],
        "commit_state": "COMMITTED",
        "idempotency_disposition": "CREATED",
        "candidate_ref": {"type": "eos.voucher_candidate", "id": CANDIDATE_ID},
        "revision_ref": {
            "type": "eos.voucher_candidate_revision",
            "id": REVISION_ID,
            "revision_no": 1,
            "hash": HASH_C,
        },
        "project_ref": {
            "type": "eos.project",
            "id": PROJECT_ID,
            "code": PROJECT_CODE,
        },
        "document_envelope_id": ENVELOPE_ID,
        "committed_at": "2026-11-12T03:00:00Z",
        "outbox_event_ref": {"type": "eos.outbox_event", "id": OUTBOX_ID},
    }
    value.update(overrides)
    return value


def _validation(**overrides):
    value = {
        "schema_version": "eos_voucher_candidate_validation.v1",
        "operation": VALIDATE_OPERATION,
        "status": "PASS",
        "tenant_id": TENANT,
        "candidate_ref": {"type": "eos.voucher_candidate", "id": CANDIDATE_ID},
        "candidate_version": 1,
        "revision_ref": {
            "type": "eos.voucher_candidate_revision",
            "id": REVISION_ID,
            "revision_no": 1,
            "hash": HASH_C,
        },
        "project_ref": {
            "type": "eos.project",
            "id": PROJECT_ID,
            "code": PROJECT_CODE,
        },
        "document_ref": {
            "type": "eos.approved_document_envelope",
            "id": ENVELOPE_ID,
            "hash": HASH_A,
        },
        "company_id": COMPANY_ID,
        "preparer_subject_id": "employee-1004",
        "accounting_period_id": PERIOD_ID,
        "recognition_date": "2026-11-12",
        "transaction_currency": "KRW",
        "functional_currency": "KRW",
        "posting_rule_release_hash": HASH_A,
        "account_policy_set_hash": HASH_B,
        "fx_rate_set_hash": HASH_D,
        "fx_evidence": {
            "mode": "SAME_CURRENCY",
            "base_currency": "KRW",
            "quote_currency": "KRW",
            "normalized_rate": "1",
            "desired_rate_date": "2026-11-12",
            "selected_rate_date": "2026-11-12",
            "staleness_business_days": 0,
            "snapshot_hash": None,
            "policy_hash": None,
        },
        "lines": [
            {
                "line_no": 1,
                "account_id": DEBIT_ACCOUNT_ID,
                "debit_original": "10000.0000",
                "credit_original": "0.0000",
                "debit_functional": "10000",
                "credit_functional": "0",
                "functional_currency": "KRW",
            },
            {
                "line_no": 2,
                "account_id": CREDIT_ACCOUNT_ID,
                "debit_original": "0.0000",
                "credit_original": "10000.0000",
                "debit_functional": "0",
                "credit_functional": "10000",
                "functional_currency": "KRW",
            },
        ],
        "totals": {
            "debit_original": "10000.0000",
            "credit_original": "10000.0000",
            "debit_functional": "10000",
            "credit_functional": "10000",
        },
        "validation_hash": HASH_E,
        "observed_at": "2026-11-12T03:00:00Z",
    }
    value.update(overrides)
    return value


def _review_event(**overrides):
    value = {
        "schema_version": "eos_candidate_review_event.v1",
        "event_id": EVENT_ID,
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 1,
        "candidate_hash": HASH_C,
        "approval_case_id": CASE_ID,
        "transition_kind": "SUBMIT",
        "from_state": "DRAFT",
        "to_state": "READY_FOR_REVIEW",
        "expected_version": 1,
        "resulting_version": 2,
        "actor_subject_id": "employee-1004",
        "reason": None,
        "validation_hash": HASH_E,
        "review_hash": HASH_A,
        "event_hash": HASH_B,
        "created_at": "2026-11-12T03:01:00Z",
    }
    value.update(overrides)
    return value


def _review_request(draft=None, create_result=None, validation=None):
    draft = draft or _draft()
    create_result = create_result or _create_result(_create_request(draft))
    return build_candidate_review_request(
        draft,
        create_result,
        validation or _validation(),
        business_operation_id=REVIEW_OPERATION_ID,
        idempotency_key="mb3-01-review-42",
        case_id=CASE_ID,
        approval_policy_id=POLICY_ID,
        correlation_id="correlation-mb3-01-review",
        causation_id="causation-mb3-01-review",
        expires_at=NOW + timedelta(days=7),
    )


def _review_receipt(request=None, **overrides):
    request = request or _review_request()
    case_input = request.payload["case"]
    case = {
        "schema_version": "eos_scoped_approval_case.v2",
        "tenant_id": TENANT,
        "case_id": CASE_ID,
        "company_id": COMPANY_ID,
        "purpose": "ACCOUNTING_POSTING",
        "scope_type": "PROJECT",
        "project_set_hash": HASH_A,
        "project_ids": [PROJECT_ID],
        "subject_ref": f"eos.voucher-candidate:{CANDIDATE_ID}",
        "subject_revision": 1,
        "subject_hash": HASH_C,
        "requester_ref": {"type": "oa.user", "id": "employee-1004"},
        "approval_policy_ref": {"id": POLICY_ID, "version": 1, "hash": HASH_B},
        "oa_decision_ref": "oa.authorization:mb3-01",
        "authorization_revision_hash": HASH_D,
        "authorization_checked_at": "2026-11-12T03:00:00Z",
        "state": "PENDING",
        "active_stage_order": 1,
        "stage_count": 1,
        "target_role_ref": "ACCOUNTING_REVIEWER",
        "version": 1,
        "case_hash": HASH_E,
        "created_business_operation_id": REVIEW_OPERATION_ID,
        "correlation_id": case_input["correlation_id"],
        "causation_id": case_input["causation_id"],
        "expires_at": case_input["expires_at"],
        "created_at": "2026-11-12T03:01:00Z",
        "updated_at": "2026-11-12T03:01:00Z",
        "decided_at": None,
        "project_bindings": [
            {
                "project_id": PROJECT_ID,
                "company_id": COMPANY_ID,
                "authorization_scope_hash": HASH_A,
            }
        ],
    }
    value = {
        "schema_version": "eos_scoped_approval_request_receipt.v2",
        "created": True,
        "tenant_id": TENANT,
        "business_operation_id": REVIEW_OPERATION_ID,
        "commit_state": "COMMITTED",
        "scoped_approval_case": case,
        "wc_publication": {
            "created": True,
            "work_item": {
                "tenant_id": TENANT,
                "approval_domain": "BUSINESS_FORMAL",
                "approval_provider_type": "EOS",
                "approval_request_id": CASE_ID,
                "business_operation_id": REVIEW_OPERATION_ID,
                "protected_request_ref": case["subject_ref"],
            },
        },
        "candidate_review": _review_event(),
    }
    value.update(overrides)
    return value


def _review_projection(**overrides):
    value = {
        "schema_version": "eos_candidate_review.v1",
        "tenant_id": TENANT,
        "candidate_id": CANDIDATE_ID,
        "state": "READY_FOR_REVIEW",
        "candidate_version": 2,
        "current_revision_no": 1,
        "events": [_review_event()],
    }
    value.update(overrides)
    return value


class RecordingTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def test_create_request_is_eos_parser_and_hash_compatible() -> None:
    draft = _draft()
    request = _create_request(draft)
    parsed = parse_create_voucher_candidate_command(request.payload)

    assert request.operation_id == CREATE_OPERATION
    assert request.path == "/internal/v2/finance/voucher-candidates"
    assert parsed.project_id == PROJECT_ID
    assert parsed.project_code == PROJECT_CODE
    assert parsed.document_envelope_id == ENVELOPE_ID
    assert parsed.lines[0].debit_original == Decimal("10000.0000")
    assert voucher_candidate_payload_hash(parsed) == request.payload["payload_hash"]
    assert draft.original_amount == Decimal("10000.0000")
    assert request.payload["candidate"]["lines"][1]["description"] is None


def test_provider_create_validate_review_contracts_are_bound() -> None:
    draft = _draft()
    create_request = _create_request(draft)
    create = admit_candidate_create_result(
        _create_result(create_request), draft=draft, request=create_request
    )
    validation_request = build_candidate_validation_request(draft, create, as_of=NOW)
    validation = admit_candidate_validation_result(
        _validation(), draft=draft, create_result=create
    )
    review_request = _review_request(draft, create, validation)

    assert validation_request.operation_id == VALIDATE_OPERATION
    assert validation_request.payload["expected_candidate_hash"] == HASH_C
    assert review_request.operation_id == "FINANCE.ACCOUNTING_APPROVAL.REQUEST"
    assert review_request.payload["case"]["purpose"] == "ACCOUNTING_POSTING"
    context = review_request.payload["case"]["accounting_review"]
    assert context["schema_version"] == "eos_accounting_review_context.v3"
    assert context["candidate_id"] == CANDIDATE_ID
    assert context["validation_hash"] == HASH_E
    assert context["original_amount"] == "10000.0000"


def test_client_runs_create_validate_review_and_projection_journey() -> None:
    draft = _draft()
    create_request = _create_request(draft)
    create_result = _create_result(create_request)
    review_request = _review_request(draft, create_result, _validation())
    transport = RecordingTransport(
        create_result,
        _validation(),
        _review_receipt(review_request),
        _review_projection(),
    )
    client = NexVoucherCandidateClient(transport)

    created = client.create(
        draft,
        business_operation_id=CREATE_OPERATION_ID,
        idempotency_key="mb3-01-candidate-42",
        trace_id="trace-mb3-01",
        correlation_id="correlation-mb3-01",
        causation_id="causation-mb3-01",
    )
    validated = client.validate(draft, created, as_of=NOW)
    receipt = client.submit_for_review(
        draft,
        created,
        validated,
        business_operation_id=REVIEW_OPERATION_ID,
        idempotency_key="mb3-01-review-42",
        case_id=CASE_ID,
        approval_policy_id=POLICY_ID,
        correlation_id="correlation-mb3-01-review",
        causation_id="causation-mb3-01-review",
        expires_at=NOW + timedelta(days=7),
    )
    projection = client.get_review(
        tenant_id=TENANT,
        subject_id="employee-1004",
        candidate_id=CANDIDATE_ID,
    )

    assert receipt["candidate_review"]["to_state"] == "READY_FOR_REVIEW"
    assert projection["state"] == "READY_FOR_REVIEW"
    assert [item.operation_id for item in transport.requests] == [
        CREATE_OPERATION,
        VALIDATE_OPERATION,
        "FINANCE.ACCOUNTING_APPROVAL.REQUEST",
        REVIEW_GET_OPERATION,
    ]
    assert transport.requests[-1].payload is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": "bad tenant"},
        {"company_id": str(uuid.uuid4())},
        {"preparer_subject_id": "bad subject"},
        {"project_id": str(uuid.uuid4())},
        {"project_code": "VO00R260001"},
        {"business_work_code": "FL0004999"},
        {"transaction_currency": "USD"},
        {"recognition_date": datetime(2026, 11, 12, tzinfo=UTC)},
        {"source_kind": "bad-kind"},
        {"source_record_ref": "bad source"},
        {"approved_document": _document(state="REVOKED", usable=False)},
        {"approved_document": _document(remaining_amount="9999.0000")},
        {"approved_document": []},
        {"approved_document": {"schema_version": "bad"}},
        {"lines": "not-lines"},
        {"lines": (_lines()[0],)},
        {
            "lines": (
                _lines()[0],
                VoucherCandidateLine(
                    CREDIT_ACCOUNT_ID,
                    Decimal(0),
                    Decimal(9999),
                    "expense-line-2",
                    None,
                    HASH_B,
                ),
            )
        },
    ],
)
def test_invalid_candidate_drafts_fail_before_provider(overrides) -> None:
    with pytest.raises(VoucherCandidateConsumerError):
        _draft(**overrides)


@pytest.mark.parametrize(
    "lines",
    [
        (
            VoucherCandidateLine("bad", Decimal(1), Decimal(0), "line-1", None, HASH_A),
            _lines()[1],
        ),
        (
            VoucherCandidateLine(
                DEBIT_ACCOUNT_ID,
                Decimal(1),
                Decimal(1),
                "line-1",
                None,
                HASH_A,
            ),
            _lines()[1],
        ),
        (
            _lines()[0],
            VoucherCandidateLine(
                CREDIT_ACCOUNT_ID,
                Decimal(0),
                Decimal(10000),
                "expense-line-1",
                None,
                HASH_B,
            ),
        ),
        (
            VoucherCandidateLine(
                DEBIT_ACCOUNT_ID,
                object(),
                Decimal(0),
                "line-1",
                None,
                HASH_A,
            ),
            _lines()[1],
        ),
        (
            VoucherCandidateLine(
                DEBIT_ACCOUNT_ID,
                Decimal("10000.00001"),
                Decimal(0),
                "line-1",
                None,
                HASH_A,
            ),
            _lines()[1],
        ),
        (
            VoucherCandidateLine(
                DEBIT_ACCOUNT_ID,
                Decimal(10000),
                Decimal(0),
                "line-1",
                "",
                HASH_A,
            ),
            _lines()[1],
        ),
        (
            VoucherCandidateLine(
                DEBIT_ACCOUNT_ID,
                Decimal(10000),
                Decimal(0),
                "line-1",
                None,
                "bad",
            ),
            _lines()[1],
        ),
        (object(), _lines()[1]),
    ],
)
def test_invalid_candidate_lines_are_rejected(lines) -> None:
    with pytest.raises(VoucherCandidateConsumerError):
        _draft(lines=lines)


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda value: value.pop("commit_state"),
            "MYBEE_CANDIDATE_CREATE_RESULT_INVALID",
        ),
        (
            lambda value: value.__setitem__("commit_state", "UNKNOWN"),
            "MYBEE_CANDIDATE_CREATE_BINDING_MISMATCH",
        ),
        (
            lambda value: value.__setitem__("tenant_id", "OTHER"),
            "MYBEE_CANDIDATE_CREATE_BINDING_MISMATCH",
        ),
        (
            lambda value: value["project_ref"].__setitem__("code", "VO00D260002"),
            "MYBEE_CANDIDATE_CREATE_BINDING_MISMATCH",
        ),
        (
            lambda value: value["revision_ref"].__setitem__("revision_no", 2),
            "MYBEE_CANDIDATE_CREATE_BINDING_MISMATCH",
        ),
        (
            lambda value: value["candidate_ref"].__setitem__("type", "bad"),
            "MYBEE_CANDIDATE_RESULT_INVALID",
        ),
        (
            lambda value: value["revision_ref"].__setitem__("id", CANDIDATE_ID),
            "MYBEE_CANDIDATE_CREATE_RESULT_INVALID",
        ),
        (
            lambda value: value.__setitem__("committed_at", "not-time"),
            "MYBEE_CANDIDATE_TIME_INVALID",
        ),
    ],
)
def test_create_result_drift_fails_closed(mutator, expected_code) -> None:
    draft = _draft()
    request = _create_request(draft)
    result = _create_result(request)
    mutator(result)
    with pytest.raises(VoucherCandidateConsumerError) as error:
        admit_candidate_create_result(result, draft=draft, request=request)
    assert error.value.code == expected_code


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.pop("status"),
        lambda value: value.__setitem__("status", "FAIL"),
        lambda value: value.__setitem__("candidate_version", True),
        lambda value: value["revision_ref"].__setitem__("hash", HASH_D),
        lambda value: value.__setitem__("posting_rule_release_hash", "bad"),
        lambda value: value.__setitem__("accounting_period_id", "bad"),
        lambda value: value.__setitem__("observed_at", "bad"),
        lambda value: value.__setitem__("observed_at", None),
        lambda value: value.__setitem__("lines", []),
        lambda value: value.__setitem__("revision_ref", None),
        lambda value: value["lines"][0].pop("account_id"),
        lambda value: value["lines"][0].__setitem__("line_no", 2),
        lambda value: value["lines"][0].__setitem__("debit_original", "0.0000"),
        lambda value: value["totals"].__setitem__("credit_original", "1.0000"),
        lambda value: value["totals"].pop("credit_original"),
        lambda value: value["fx_evidence"].__setitem__("mode", "UNKNOWN"),
        lambda value: value["fx_evidence"].__setitem__("selected_rate_date", "bad"),
        lambda value: value["fx_evidence"].__setitem__("desired_rate_date", None),
        lambda value: value["fx_evidence"].__setitem__("normalized_rate", "2"),
        lambda value: value["fx_evidence"].__setitem__("normalized_rate", "0"),
        lambda value: value["fx_evidence"].__setitem__("staleness_business_days", True),
    ],
)
def test_validation_drift_fails_closed(mutator) -> None:
    draft = _draft()
    create = _create_result(_create_request(draft))
    validation = _validation()
    mutator(validation)
    with pytest.raises(VoucherCandidateConsumerError):
        admit_candidate_validation_result(validation, draft=draft, create_result=create)


def test_approved_snapshot_fx_evidence_is_admitted() -> None:
    validation = _validation(
        transaction_currency="USD",
        functional_currency="KRW",
        fx_evidence={
            "mode": "APPROVED_SNAPSHOT",
            "base_currency": "USD",
            "quote_currency": "KRW",
            "normalized_rate": "1400.25",
            "desired_rate_date": "2026-11-12",
            "selected_rate_date": "2026-11-11",
            "staleness_business_days": 1,
            "snapshot_hash": HASH_A,
            "policy_hash": HASH_B,
        },
    )
    draft = _draft(
        transaction_currency="USD",
        approved_document=_document(approved_currency="USD"),
    )
    admitted = admit_candidate_validation_result(
        validation,
        draft=draft,
        create_result=_create_result(_create_request(draft)),
    )
    assert admitted["fx_evidence"]["mode"] == "APPROVED_SNAPSHOT"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.pop("events"),
        lambda value: value.__setitem__("state", "POSTED"),
        lambda value: value.__setitem__("candidate_version", False),
        lambda value: value.__setitem__("events", "bad"),
        lambda value: value["events"][0].pop("event_hash"),
        lambda value: value["events"][0].__setitem__("candidate_id", str(uuid.uuid4())),
        lambda value: value["events"][0].__setitem__("resulting_version", 9),
        lambda value: value["events"][0].__setitem__("event_hash", "bad"),
        lambda value: value["events"][0].__setitem__("created_at", "bad"),
    ],
)
def test_review_projection_drift_fails_closed(mutator) -> None:
    value = _review_projection()
    mutator(value)
    with pytest.raises(VoucherCandidateConsumerError):
        admit_candidate_review_projection(
            value, tenant_id=TENANT, candidate_id=CANDIDATE_ID
        )


def test_review_receipt_requires_candidate_validation_lineage() -> None:
    draft = _draft()
    create = _create_result(_create_request(draft))
    validation = _validation()
    receipt = _review_receipt(_review_request(draft, create, validation))
    receipt["candidate_review"]["validation_hash"] = HASH_D
    client = NexVoucherCandidateClient(RecordingTransport(receipt))

    with pytest.raises(VoucherCandidateConsumerError) as error:
        client.submit_for_review(
            draft,
            create,
            validation,
            business_operation_id=REVIEW_OPERATION_ID,
            idempotency_key="mb3-01-review-42",
            case_id=CASE_ID,
            approval_policy_id=POLICY_ID,
            correlation_id="correlation-mb3-01-review",
            causation_id="causation-mb3-01-review",
            expires_at=NOW + timedelta(days=7),
        )
    assert error.value.code == "MYBEE_CANDIDATE_REVIEW_BINDING_MISMATCH"


def test_malformed_review_receipt_is_mapped_to_consumer_error() -> None:
    draft = _draft()
    create = _create_result(_create_request(draft))
    validation = _validation()
    receipt = _review_receipt(_review_request(draft, create, validation))
    receipt["candidate_review"]["event_hash"] = "bad"
    client = NexVoucherCandidateClient(RecordingTransport(receipt))

    with pytest.raises(VoucherCandidateConsumerError) as error:
        client.submit_for_review(
            draft,
            create,
            validation,
            business_operation_id=REVIEW_OPERATION_ID,
            idempotency_key="mb3-01-review-42",
            case_id=CASE_ID,
            approval_policy_id=POLICY_ID,
            correlation_id="correlation-mb3-01-review",
            causation_id="causation-mb3-01-review",
            expires_at=NOW + timedelta(days=7),
        )
    assert error.value.code == "MYBEE_CANDIDATE_REVIEW_RECEIPT_INVALID"


def test_return_review_event_may_omit_validation_hash() -> None:
    projection = _review_projection(
        state="RETURNED_FOR_CORRECTION",
        events=[
            _review_event(
                transition_kind="RETURN",
                from_state="READY_FOR_REVIEW",
                to_state="RETURNED_FOR_CORRECTION",
                validation_hash=None,
                reason="Correction required",
            )
        ],
    )
    admitted = admit_candidate_review_projection(
        projection, tenant_id=TENANT, candidate_id=CANDIDATE_ID
    )
    assert admitted["events"][0]["validation_hash"] is None


class _Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.value


def test_http_transport_sends_signed_tenant_scoped_json(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(consumer_module, "urlopen", fake_urlopen)
    transport = HttpVoucherCandidateProviderTransport(
        eos_base_url="http://127.0.0.1:8087/root",
        service_token="secret-token",
        timeout_seconds=3.5,
    )
    result = transport.send(
        VoucherCandidateProviderRequest(
            method="POST",
            path="/candidate",
            operation_id="TEST",
            tenant_id=TENANT,
            subject_id="employee-1004",
            payload={"amount": "1.0000"},
        )
    )

    outgoing = captured["request"]
    assert result == {"ok": True}
    assert outgoing.full_url == "http://127.0.0.1:8087/root/candidate"
    assert outgoing.headers["Authorization"] == "Bearer secret-token"
    assert outgoing.headers["X-nex-tenant-id"] == TENANT
    assert json.loads(outgoing.data) == {"amount": "1.0000"}
    assert captured["timeout"] == 3.5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"eos_base_url": "file:///tmp/eos", "service_token": "token"},
        {"eos_base_url": "http://eos", "service_token": ""},
        {
            "eos_base_url": "http://eos",
            "service_token": "token",
            "timeout_seconds": 0,
        },
    ],
)
def test_http_transport_configuration_is_fail_closed(kwargs) -> None:
    with pytest.raises(VoucherCandidateConsumerError):
        HttpVoucherCandidateProviderTransport(**kwargs)


@pytest.mark.parametrize(
    ("failure", "expected_code", "status"),
    [
        (
            HTTPError(
                "http://eos",
                409,
                "conflict",
                {},
                BytesIO(b'{"error_code":"EOS_CONFLICT","retryable":false}'),
            ),
            "EOS_CONFLICT",
            409,
        ),
        (URLError("offline"), "EOS_VOUCHER_CANDIDATE_UNAVAILABLE", 503),
        (TimeoutError(), "EOS_VOUCHER_CANDIDATE_UNAVAILABLE", 503),
    ],
)
def test_http_transport_maps_provider_failures(
    monkeypatch, failure, expected_code, status
) -> None:
    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(consumer_module, "urlopen", fail)
    transport = HttpVoucherCandidateProviderTransport(
        eos_base_url="http://eos", service_token="token"
    )
    with pytest.raises(VoucherCandidateConsumerError) as error:
        transport.send(
            VoucherCandidateProviderRequest(
                "GET", "/candidate", "TEST", TENANT, "employee-1004"
            )
        )
    assert error.value.code == expected_code
    assert error.value.status_code == status


def test_http_error_with_non_json_body_uses_safe_default(monkeypatch) -> None:
    failure = HTTPError("http://eos", 503, "unavailable", {}, BytesIO(b"not-json"))

    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(consumer_module, "urlopen", fail)
    transport = HttpVoucherCandidateProviderTransport(
        eos_base_url="http://eos", service_token="token"
    )
    with pytest.raises(VoucherCandidateConsumerError) as error:
        transport.send(
            VoucherCandidateProviderRequest(
                "GET", "/candidate", "TEST", TENANT, "employee-1004"
            )
        )
    assert error.value.code == "EOS_VOUCHER_CANDIDATE_REJECTED"
    assert error.value.retryable is True


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
def test_http_transport_rejects_non_object_json(monkeypatch, body) -> None:
    monkeypatch.setattr(consumer_module, "urlopen", lambda *_a, **_k: _Response(body))
    transport = HttpVoucherCandidateProviderTransport(
        eos_base_url="http://eos", service_token="token"
    )
    with pytest.raises(VoucherCandidateConsumerError) as error:
        transport.send(
            VoucherCandidateProviderRequest(
                "GET", "/candidate", "TEST", TENANT, "employee-1004"
            )
        )
    assert error.value.code == "EOS_VOUCHER_CANDIDATE_RESPONSE_INVALID"


def test_contract_surface_has_no_direct_gl_write_or_private_provider_import() -> None:
    source = inspect.getsource(consumer_module)
    assert "nex_eos" not in source
    assert "sqlalchemy" not in source
    assert "psycopg" not in source
    assert "GL.POST" not in source
    assert "voucher-drafts" not in source

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    assert (
        spec["paths"]["/internal/v2/finance/voucher-candidates"]["post"]["operationId"]
        == CREATE_OPERATION
    )
    assert (
        spec["paths"][
            "/internal/v2/finance/voucher-candidates/{candidate_id}/validation"
        ]["post"]["operationId"]
        == VALIDATE_OPERATION
    )
    assert (
        spec["paths"]["/internal/v2/finance/voucher-candidates/{candidate_id}/review"][
            "get"
        ]["operationId"]
        == REVIEW_GET_OPERATION
    )


def test_request_and_response_helpers_reject_wrong_types() -> None:
    with pytest.raises(VoucherCandidateConsumerError):
        build_candidate_create_request(
            object(),
            business_operation_id=CREATE_OPERATION_ID,
            idempotency_key="key",
            trace_id="trace",
            correlation_id="correlation",
            causation_id="causation",
        )
    with pytest.raises(VoucherCandidateConsumerError):
        admit_candidate_create_result([], draft=_draft(), request=_create_request())
    with pytest.raises(VoucherCandidateConsumerError):
        admit_candidate_validation_result(
            [], draft=_draft(), create_result=_create_result()
        )
    with pytest.raises(VoucherCandidateConsumerError):
        admit_candidate_review_projection(
            [], tenant_id=TENANT, candidate_id=CANDIDATE_ID
        )


def test_replayed_create_receipt_is_accepted() -> None:
    draft = _draft()
    request = _create_request(draft)
    admitted = admit_candidate_create_result(
        _create_result(request, idempotency_disposition="REPLAYED"),
        draft=draft,
        request=request,
    )
    assert admitted["idempotency_disposition"] == "REPLAYED"


def test_validation_request_requires_aware_time() -> None:
    with pytest.raises(VoucherCandidateConsumerError) as error:
        build_candidate_validation_request(
            _draft(), _create_result(), as_of=NOW.replace(tzinfo=None)
        )
    assert error.value.code == "MYBEE_CANDIDATE_TIME_INVALID"


def test_malformed_review_request_is_mapped_to_consumer_error() -> None:
    draft = _draft()
    with pytest.raises(VoucherCandidateConsumerError) as error:
        build_candidate_review_request(
            draft,
            _create_result(_create_request(draft)),
            _validation(),
            business_operation_id=REVIEW_OPERATION_ID,
            idempotency_key="mb3-01-review-42",
            case_id=CASE_ID,
            approval_policy_id=POLICY_ID,
            correlation_id="bad correlation",
            causation_id="causation-mb3-01-review",
            expires_at=NOW + timedelta(days=7),
        )
    assert error.value.code == "MYBEE_CANDIDATE_REVIEW_REQUEST_INVALID"


def test_review_receipt_without_candidate_event_is_rejected() -> None:
    draft = _draft()
    create = _create_result(_create_request(draft))
    validation = _validation()
    receipt = _review_receipt(_review_request(draft, create, validation))
    receipt.pop("candidate_review")
    client = NexVoucherCandidateClient(RecordingTransport(receipt))
    with pytest.raises(VoucherCandidateConsumerError) as error:
        client.submit_for_review(
            draft,
            create,
            validation,
            business_operation_id=REVIEW_OPERATION_ID,
            idempotency_key="mb3-01-review-42",
            case_id=CASE_ID,
            approval_policy_id=POLICY_ID,
            correlation_id="correlation-mb3-01-review",
            causation_id="causation-mb3-01-review",
            expires_at=NOW + timedelta(days=7),
        )
    assert error.value.code == "MYBEE_CANDIDATE_REVIEW_BINDING_MISMATCH"


def test_copying_provider_values_does_not_mutate_draft() -> None:
    document = _document()
    draft = _draft(approved_document=document)
    document["state"] = "REVOKED"
    assert draft.approved_document["state"] == "ACTIVE"
    assert copy.deepcopy(dict(draft.approved_document))["state"] == "ACTIVE"
