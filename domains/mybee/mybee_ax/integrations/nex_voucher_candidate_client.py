"""Proof-bound MyBee consumer for the canonical EOS VoucherCandidate v2 flow."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from nex_runtime.semantic_hashes import (
    canonical_json,
    nsl_write_payload_hash_ref,
    validate_hash_ref,
)

from ..domain.documents import (
    ApprovedDocumentContractError,
    admit_approved_document_envelope,
)
from .nex_approval_client import (
    EosScopedApprovalRequest,
    ScopedApprovalContractError,
    admit_scoped_approval_receipt,
    build_scoped_approval_request,
)

CREATE_OPERATION = "FINANCE.VOUCHER_CANDIDATE.CREATE_V2"
VALIDATE_OPERATION = "FINANCE.VOUCHER_CANDIDATE.VALIDATE"
REVIEW_GET_OPERATION = "FINANCE.VOUCHER_CANDIDATE.REVIEW_GET"
CREATE_PATH = "/internal/v2/finance/voucher-candidates"
VALIDATE_PATH = "/internal/v2/finance/voucher-candidates/{candidate_id}/validation"
REVIEW_PATH = "/internal/v2/finance/voucher-candidates/{candidate_id}/review"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_CREATE_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "commit_state",
        "idempotency_disposition",
        "candidate_ref",
        "revision_ref",
        "project_ref",
        "document_envelope_id",
        "committed_at",
        "outbox_event_ref",
    }
)
_VALIDATION_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "status",
        "tenant_id",
        "candidate_ref",
        "candidate_version",
        "revision_ref",
        "project_ref",
        "document_ref",
        "company_id",
        "preparer_subject_id",
        "accounting_period_id",
        "recognition_date",
        "transaction_currency",
        "functional_currency",
        "posting_rule_release_hash",
        "account_policy_set_hash",
        "fx_rate_set_hash",
        "fx_evidence",
        "lines",
        "totals",
        "validation_hash",
        "observed_at",
    }
)


class VoucherCandidateConsumerError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class VoucherCandidateLine:
    account_id: str
    debit_original: Decimal
    credit_original: Decimal
    source_record_line_ref: str
    description: str | None
    evidence_hash: str


@dataclass(frozen=True)
class VoucherCandidateDraft:
    tenant_id: str
    company_id: str
    preparer_subject_id: str
    project_id: str
    project_code: str
    approved_document: Mapping[str, Any]
    source_kind: str
    source_record_ref: str
    business_work_code: str
    transaction_currency: str
    recognition_date: date
    lines: tuple[VoucherCandidateLine, ...]

    @property
    def original_amount(self) -> Decimal:
        return sum((line.debit_original for line in self.lines), Decimal(0))


@dataclass(frozen=True)
class VoucherCandidateProviderRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    subject_id: str
    payload: Mapping[str, Any] | None = None


class VoucherCandidateProviderTransport(Protocol):
    def send(self, request: VoucherCandidateProviderRequest) -> Mapping[str, Any]: ...


class NexVoucherCandidateClient:
    """Consumes EOS Candidate APIs without owning persistence or GL mutation."""

    def __init__(self, transport: VoucherCandidateProviderTransport) -> None:
        self._transport = transport

    def create(
        self,
        draft: VoucherCandidateDraft,
        *,
        business_operation_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
    ) -> Mapping[str, Any]:
        request = build_candidate_create_request(
            draft,
            business_operation_id=business_operation_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return admit_candidate_create_result(
            self._transport.send(request),
            draft=draft,
            request=request,
        )

    def validate(
        self,
        draft: VoucherCandidateDraft,
        create_result: Mapping[str, Any],
        *,
        as_of: datetime,
    ) -> Mapping[str, Any]:
        request = build_candidate_validation_request(
            draft,
            create_result,
            as_of=as_of,
        )
        return admit_candidate_validation_result(
            self._transport.send(request),
            draft=draft,
            create_result=create_result,
        )

    def submit_for_review(
        self,
        draft: VoucherCandidateDraft,
        create_result: Mapping[str, Any],
        validation: Mapping[str, Any],
        *,
        business_operation_id: str,
        idempotency_key: str,
        case_id: str,
        approval_policy_id: str,
        correlation_id: str,
        causation_id: str,
        expires_at: datetime,
    ) -> Mapping[str, Any]:
        request = build_candidate_review_request(
            draft,
            create_result,
            validation,
            business_operation_id=business_operation_id,
            idempotency_key=idempotency_key,
            case_id=case_id,
            approval_policy_id=approval_policy_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            expires_at=expires_at,
        )
        try:
            receipt = admit_scoped_approval_receipt(
                self._transport.send(request),
                tenant_id=draft.tenant_id,
                business_operation_id=business_operation_id,
                case_id=case_id,
            )
        except ScopedApprovalContractError as exc:
            raise _invalid("MYBEE_CANDIDATE_REVIEW_RECEIPT_INVALID", str(exc)) from exc
        _require_review_receipt_binding(receipt, create_result, validation)
        return receipt

    def get_review(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        candidate_id: str,
    ) -> Mapping[str, Any]:
        request = VoucherCandidateProviderRequest(
            method="GET",
            path=REVIEW_PATH.format(candidate_id=_uuid("candidate_id", candidate_id)),
            operation_id=REVIEW_GET_OPERATION,
            tenant_id=_scoped_id("tenant_id", tenant_id, 128),
            subject_id=_scoped_id("subject_id", subject_id, 128),
        )
        return admit_candidate_review_projection(
            self._transport.send(request),
            tenant_id=request.tenant_id,
            candidate_id=candidate_id,
        )


class HttpVoucherCandidateProviderTransport:
    def __init__(
        self,
        *,
        eos_base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlparse(eos_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _invalid("MYBEE_CANDIDATE_BASE_URL_INVALID", "http(s) URL required")
        if not isinstance(service_token, str) or not service_token.strip():
            raise _invalid(
                "MYBEE_CANDIDATE_SERVICE_TOKEN_MISSING", "service token is required"
            )
        if timeout_seconds <= 0:
            raise _invalid(
                "MYBEE_CANDIDATE_TIMEOUT_INVALID", "positive timeout required"
            )
        self._base_url = eos_base_url.rstrip("/") + "/"
        self._service_token = service_token.strip()
        self._timeout_seconds = float(timeout_seconds)

    def send(self, request: VoucherCandidateProviderRequest) -> Mapping[str, Any]:
        body = (
            canonical_json(dict(request.payload)).encode("utf-8")
            if request.payload is not None
            else None
        )
        outgoing = Request(
            urljoin(self._base_url, request.path.lstrip("/")),
            data=body,
            method=request.method,
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "X-NeX-Tenant-Id": request.tenant_id,
                "X-NeX-Subject-Id": request.subject_id,
            },
        )
        try:
            with urlopen(outgoing, timeout=self._timeout_seconds) as response:
                return _json_object(response.read())
        except HTTPError as exc:
            problem = _optional_json_object(exc.read())
            raise VoucherCandidateConsumerError(
                str(problem.get("error_code", "EOS_VOUCHER_CANDIDATE_REJECTED")),
                "EOS rejected the VoucherCandidate request",
                status_code=exc.code,
                retryable=bool(problem.get("retryable", exc.code >= 500)),
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise VoucherCandidateConsumerError(
                "EOS_VOUCHER_CANDIDATE_UNAVAILABLE",
                "EOS VoucherCandidate endpoint is unavailable",
                status_code=503,
                retryable=True,
            ) from exc


def build_voucher_candidate_draft(
    *,
    tenant_id: str,
    company_id: str,
    preparer_subject_id: str,
    project_id: str,
    project_code: str,
    approved_document: Mapping[str, Any],
    source_kind: str,
    source_record_ref: str,
    business_work_code: str,
    transaction_currency: str,
    recognition_date: date,
    lines: Sequence[VoucherCandidateLine],
) -> VoucherCandidateDraft:
    admitted_tenant = _scoped_id("tenant_id", tenant_id, 128)
    if not isinstance(approved_document, Mapping):
        raise _invalid("MYBEE_CANDIDATE_DOCUMENT_INVALID", "document must be an object")
    try:
        document = admit_approved_document_envelope(
            approved_document,
            tenant_id=admitted_tenant,
            envelope_id=str(approved_document.get("envelope_id")),
        )
    except ApprovedDocumentContractError as exc:
        raise _invalid("MYBEE_CANDIDATE_DOCUMENT_INVALID", str(exc)) from exc
    normalized_project_id = _uuid("project_id", project_id)
    normalized_project_code = _project_code(project_code, tenant_id=admitted_tenant)
    normalized_company_id = _uuid("company_id", company_id)
    normalized_work_code = _pattern(
        "business_work_code", business_work_code, _WORK_CODE
    )
    normalized_currency = _pattern(
        "transaction_currency", transaction_currency, _CURRENCY
    )
    normalized_lines = _lines(lines)
    original_debit = sum((line.debit_original for line in normalized_lines), Decimal(0))
    original_credit = sum(
        (line.credit_original for line in normalized_lines), Decimal(0)
    )
    if original_debit != original_credit:
        raise _invalid(
            "MYBEE_CANDIDATE_UNBALANCED", "original debits and credits differ"
        )
    if (
        document["company_id"] != normalized_company_id
        or normalized_project_id not in document["allowed_project_ids"]
        or normalized_project_code not in document.get("allowed_project_codes", [])
        or document["work_code"] != normalized_work_code
        or document["approved_currency"] != normalized_currency
        or document["state"] != "ACTIVE"
        or document["usable"] is not True
        or original_debit > Decimal(str(document["remaining_amount"]))
    ):
        raise _conflict(
            "MYBEE_CANDIDATE_DOCUMENT_BINDING_MISMATCH",
            "Candidate does not fit the active approved-document allowance",
        )
    if not isinstance(recognition_date, date) or isinstance(recognition_date, datetime):
        raise _invalid(
            "MYBEE_CANDIDATE_DATE_INVALID", "recognition_date must be a date"
        )
    return VoucherCandidateDraft(
        tenant_id=admitted_tenant,
        company_id=normalized_company_id,
        preparer_subject_id=_scoped_id("preparer_subject_id", preparer_subject_id, 128),
        project_id=normalized_project_id,
        project_code=normalized_project_code,
        approved_document=document,
        source_kind=_pattern("source_kind", source_kind, _CODE),
        source_record_ref=_scoped_id("source_record_ref", source_record_ref, 256),
        business_work_code=normalized_work_code,
        transaction_currency=normalized_currency,
        recognition_date=recognition_date,
        lines=normalized_lines,
    )


def build_candidate_create_request(
    draft: VoucherCandidateDraft,
    *,
    business_operation_id: str,
    idempotency_key: str,
    trace_id: str,
    correlation_id: str,
    causation_id: str,
) -> VoucherCandidateProviderRequest:
    if not isinstance(draft, VoucherCandidateDraft):
        raise _invalid("MYBEE_CANDIDATE_DRAFT_INVALID", "draft type is invalid")
    business_payload = _candidate_business_payload(draft)
    payload = {
        **business_payload,
        "business_operation_id": _uuid("business_operation_id", business_operation_id),
        "idempotency_key": _text("idempotency_key", idempotency_key, 256),
        "payload_hash": nsl_write_payload_hash_ref(business_payload),
        "trace": {
            "trace_id": _scoped_id("trace_id", trace_id, 128),
            "correlation_id": _scoped_id("correlation_id", correlation_id, 128),
            "causation_id": _scoped_id("causation_id", causation_id, 128),
        },
    }
    return VoucherCandidateProviderRequest(
        method="POST",
        path=CREATE_PATH,
        operation_id=CREATE_OPERATION,
        tenant_id=draft.tenant_id,
        subject_id=draft.preparer_subject_id,
        payload=MappingProxyType(payload),
    )


def build_candidate_validation_request(
    draft: VoucherCandidateDraft,
    create_result: Mapping[str, Any],
    *,
    as_of: datetime,
) -> VoucherCandidateProviderRequest:
    candidate_id = _candidate_result_binding(create_result, draft)["candidate_id"]
    revision = create_result["revision_ref"]
    return VoucherCandidateProviderRequest(
        method="POST",
        path=VALIDATE_PATH.format(candidate_id=candidate_id),
        operation_id=VALIDATE_OPERATION,
        tenant_id=draft.tenant_id,
        subject_id=draft.preparer_subject_id,
        payload=MappingProxyType(
            {
                "schema_version": "eos_voucher_candidate_validate.v1",
                "tenant_id": draft.tenant_id,
                "expected_revision_no": int(revision["revision_no"]),
                "expected_candidate_hash": _hash_ref(
                    "revision_ref.hash", revision["hash"]
                ),
                "as_of": _timestamp("as_of", as_of),
            }
        ),
    )


def build_candidate_review_request(
    draft: VoucherCandidateDraft,
    create_result: Mapping[str, Any],
    validation: Mapping[str, Any],
    *,
    business_operation_id: str,
    idempotency_key: str,
    case_id: str,
    approval_policy_id: str,
    correlation_id: str,
    causation_id: str,
    expires_at: datetime,
) -> VoucherCandidateProviderRequest:
    admitted = admit_candidate_validation_result(
        validation,
        draft=draft,
        create_result=create_result,
    )
    candidate_id = admitted["candidate_ref"]["id"]
    fx = admitted["fx_evidence"]
    totals = admitted["totals"]
    principal = draft.approved_document["approved_by_principal_ref"]
    rate_publication = (
        "SAME_CURRENCY"
        if fx["mode"] == "SAME_CURRENCY"
        else (
            f"{fx['mode']}:{fx['selected_rate_date']}:"
            f"{fx['base_currency']}/{fx['quote_currency']}"
        )
    )
    review = {
        "schema_version": "eos_accounting_review_context.v3",
        "candidate_id": candidate_id,
        "candidate_revision": admitted["revision_ref"]["revision_no"],
        "candidate_hash": admitted["revision_ref"]["hash"],
        "candidate_version": admitted["candidate_version"],
        "validation_hash": admitted["validation_hash"],
        "validation_observed_at": admitted["observed_at"],
        "document_envelope_hash": admitted["document_ref"]["hash"],
        "fx_rate_set_hash": admitted["fx_rate_set_hash"],
        "rule_release_hash": admitted["posting_rule_release_hash"],
        "accounting_period_id": admitted["accounting_period_id"],
        "candidate_preparer_subject_id": admitted["preparer_subject_id"],
        "business_approver_subject_ids": [principal["id"]],
        "original_currency": admitted["transaction_currency"],
        "original_amount": totals["debit_original"],
        "market_base_rate": fx["normalized_rate"],
        "rate_reference_date": fx["selected_rate_date"],
        "rate_publication": rate_publication,
        "functional_currency": admitted["functional_currency"],
        "functional_amount": totals["debit_functional"],
        "fx_exception": None,
    }
    try:
        request: EosScopedApprovalRequest = build_scoped_approval_request(
            tenant_id=draft.tenant_id,
            business_operation_id=business_operation_id,
            idempotency_key=idempotency_key,
            case_id=case_id,
            company_id=draft.company_id,
            purpose="ACCOUNTING_POSTING",
            scope_type="PROJECT",
            project_ids=[draft.project_id],
            subject_ref=f"eos.voucher-candidate:{candidate_id}",
            subject_revision=admitted["revision_ref"]["revision_no"],
            subject_hash=admitted["revision_ref"]["hash"],
            requester_subject_id=draft.preparer_subject_id,
            approval_policy_id=approval_policy_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            accounting_review=review,
            expires_at=expires_at,
        )
    except ScopedApprovalContractError as exc:
        raise _invalid("MYBEE_CANDIDATE_REVIEW_REQUEST_INVALID", str(exc)) from exc
    return VoucherCandidateProviderRequest(
        method=request.method,
        path=request.path,
        operation_id=request.operation_id,
        tenant_id=draft.tenant_id,
        subject_id=draft.preparer_subject_id,
        payload=request.payload,
    )


def admit_candidate_create_result(
    value: object,
    *,
    draft: VoucherCandidateDraft,
    request: VoucherCandidateProviderRequest,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _CREATE_RESULT_FIELDS:
        raise _invalid("MYBEE_CANDIDATE_CREATE_RESULT_INVALID", "result fields drifted")
    result = dict(value)
    if (
        result["schema_version"] != "eos_voucher_candidate_create_result.v2"
        or result["commit_state"] != "COMMITTED"
        or result["idempotency_disposition"] not in {"CREATED", "REPLAYED"}
        or result["tenant_id"] != draft.tenant_id
        or result["business_operation_id"] != request.payload["business_operation_id"]
        or result["idempotency_key"] != request.payload["idempotency_key"]
        or result["payload_hash"] != request.payload["payload_hash"]
        or result["document_envelope_id"] != draft.approved_document["envelope_id"]
    ):
        raise _conflict(
            "MYBEE_CANDIDATE_CREATE_BINDING_MISMATCH",
            "EOS create receipt does not bind the submitted Candidate",
        )
    binding = _candidate_result_binding(result, draft)
    _entity_ref("outbox_event_ref", result["outbox_event_ref"], "eos.outbox_event")
    _timestamp("committed_at", result["committed_at"])
    if binding["candidate_id"] == binding["revision_id"]:
        raise _invalid(
            "MYBEE_CANDIDATE_CREATE_RESULT_INVALID", "entity identities collided"
        )
    return MappingProxyType(result)


def admit_candidate_validation_result(
    value: object,
    *,
    draft: VoucherCandidateDraft,
    create_result: Mapping[str, Any],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _VALIDATION_FIELDS:
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "fields drifted")
    result = dict(value)
    binding = _candidate_result_binding(create_result, draft)
    revision = result.get("revision_ref")
    project = result.get("project_ref")
    document = result.get("document_ref")
    fx = result.get("fx_evidence")
    totals = result.get("totals")
    if not all(
        isinstance(item, Mapping) for item in (revision, project, document, fx, totals)
    ):
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "evidence is incomplete")
    if (
        result["schema_version"] != "eos_voucher_candidate_validation.v1"
        or result["operation"] != VALIDATE_OPERATION
        or result["status"] != "PASS"
        or result["tenant_id"] != draft.tenant_id
        or result.get("candidate_ref")
        != {"type": "eos.voucher_candidate", "id": binding["candidate_id"]}
        or not _is_positive_int(result["candidate_version"])
        or revision.get("type") != "eos.voucher_candidate_revision"
        or revision.get("id") != binding["revision_id"]
        or revision.get("revision_no") != binding["revision_no"]
        or revision.get("hash") != binding["candidate_hash"]
        or project
        != {"type": "eos.project", "id": draft.project_id, "code": draft.project_code}
        or document
        != {
            "type": "eos.approved_document_envelope",
            "id": draft.approved_document["envelope_id"],
            "hash": draft.approved_document["document_content_hash"],
        }
        or result["company_id"] != draft.company_id
        or result["preparer_subject_id"] != draft.preparer_subject_id
        or result["recognition_date"] != draft.recognition_date.isoformat()
        or result["transaction_currency"] != draft.transaction_currency
    ):
        raise _conflict(
            "MYBEE_CANDIDATE_VALIDATION_BINDING_MISMATCH",
            "EOS validation does not bind the submitted Candidate",
        )
    for field in (
        "posting_rule_release_hash",
        "account_policy_set_hash",
        "fx_rate_set_hash",
        "validation_hash",
    ):
        _hash_ref(field, result[field])
    _uuid("accounting_period_id", result["accounting_period_id"])
    _timestamp("observed_at", result["observed_at"])
    _admit_fx_evidence(fx)
    _admit_validation_totals(totals)
    if not isinstance(result["lines"], list) or not result["lines"]:
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "lines are missing")
    for expected_line_no, line in enumerate(result["lines"], start=1):
        _admit_validation_line(line, expected_line_no=expected_line_no)
    return MappingProxyType(result)


def admit_candidate_review_projection(
    value: object,
    *,
    tenant_id: str,
    candidate_id: str,
) -> Mapping[str, Any]:
    fields = {
        "schema_version",
        "tenant_id",
        "candidate_id",
        "state",
        "candidate_version",
        "current_revision_no",
        "events",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("MYBEE_CANDIDATE_REVIEW_INVALID", "projection fields drifted")
    projection = dict(value)
    if (
        projection["schema_version"] != "eos_candidate_review.v1"
        or projection["tenant_id"] != _scoped_id("tenant_id", tenant_id, 128)
        or projection["candidate_id"] != _uuid("candidate_id", candidate_id)
        or projection["state"]
        not in {"DRAFT", "READY_FOR_REVIEW", "RETURNED_FOR_CORRECTION"}
        or not _is_positive_int(projection["candidate_version"])
        or not _is_positive_int(projection["current_revision_no"])
        or not isinstance(projection["events"], list)
    ):
        raise _conflict(
            "MYBEE_CANDIDATE_REVIEW_BINDING_MISMATCH", "review projection drifted"
        )
    for event in projection["events"]:
        _admit_review_event(event, candidate_id=projection["candidate_id"])
    return MappingProxyType(projection)


def _candidate_business_payload(draft: VoucherCandidateDraft) -> dict[str, Any]:
    document = draft.approved_document
    return {
        "schema_version": "eos_voucher_candidate_create.v2",
        "tenant_id": draft.tenant_id,
        "company_id": draft.company_id,
        "preparer_subject_id": draft.preparer_subject_id,
        "project_ref": {
            "type": "eos.project",
            "id": draft.project_id,
            "code": draft.project_code,
        },
        "business_approval": {
            "envelope_id": document["envelope_id"],
            "approved_document_id": document["approved_document_id"],
            "document_revision": document["document_revision"],
            "approved_document_hash": document["document_content_hash"],
            "attachment_manifest_hash": document["attachment_manifest_hash"],
        },
        "candidate": {
            "source_kind": draft.source_kind,
            "source_record_ref": draft.source_record_ref,
            "business_work_code": draft.business_work_code,
            "transaction_currency": draft.transaction_currency,
            "recognition_date": draft.recognition_date.isoformat(),
            "lines": [
                {
                    "line_no": line_no,
                    "account_ref": {"type": "eos.account", "id": line.account_id},
                    "debit_original": _money_text(line.debit_original),
                    "credit_original": _money_text(line.credit_original),
                    "source_record_line_ref": line.source_record_line_ref,
                    "description": line.description,
                    "evidence_hash": line.evidence_hash,
                }
                for line_no, line in enumerate(draft.lines, start=1)
            ],
        },
    }


def _candidate_result_binding(
    result: Mapping[str, Any], draft: VoucherCandidateDraft
) -> dict[str, Any]:
    candidate = _entity_ref(
        "candidate_ref", result.get("candidate_ref"), "eos.voucher_candidate"
    )
    revision = result.get("revision_ref")
    project = result.get("project_ref")
    if (
        not isinstance(revision, Mapping)
        or set(revision) != {"type", "id", "revision_no", "hash"}
        or revision["type"] != "eos.voucher_candidate_revision"
        or revision["revision_no"] != 1
        or not isinstance(project, Mapping)
        or project
        != {"type": "eos.project", "id": draft.project_id, "code": draft.project_code}
    ):
        raise _conflict(
            "MYBEE_CANDIDATE_CREATE_BINDING_MISMATCH", "result lineage drifted"
        )
    return {
        "candidate_id": candidate["id"],
        "revision_id": _uuid("revision_ref.id", revision["id"]),
        "revision_no": revision["revision_no"],
        "candidate_hash": _hash_ref("revision_ref.hash", revision["hash"]),
    }


def _require_review_receipt_binding(
    receipt: Mapping[str, Any],
    create_result: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> None:
    case = receipt["scoped_approval_case"]
    event = receipt.get("candidate_review")
    candidate_id = validation["candidate_ref"]["id"]
    expected_subject = f"eos.voucher-candidate:{candidate_id}"
    if (
        case["purpose"] != "ACCOUNTING_POSTING"
        or case["subject_ref"] != expected_subject
        or case["subject_revision"] != validation["revision_ref"]["revision_no"]
        or case["subject_hash"] != validation["revision_ref"]["hash"]
        or not isinstance(event, Mapping)
        or event.get("transition_kind") != "SUBMIT"
        or event.get("candidate_id") != candidate_id
        or event.get("candidate_hash") != validation["revision_ref"]["hash"]
        or event.get("validation_hash") != validation["validation_hash"]
        or event.get("approval_case_id") != case["case_id"]
        or create_result["candidate_ref"]["id"] != candidate_id
    ):
        raise _conflict(
            "MYBEE_CANDIDATE_REVIEW_BINDING_MISMATCH",
            "EOS review receipt does not bind Candidate validation evidence",
        )


def _lines(value: Sequence[VoucherCandidateLine]) -> tuple[VoucherCandidateLine, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("MYBEE_CANDIDATE_LINES_INVALID", "lines must be an array")
    if not 2 <= len(value) <= 1000:
        raise _invalid("MYBEE_CANDIDATE_LINES_INVALID", "2..1000 lines required")
    admitted = []
    source_refs = set()
    for raw in value:
        if not isinstance(raw, VoucherCandidateLine):
            raise _invalid("MYBEE_CANDIDATE_LINES_INVALID", "line type is invalid")
        debit = _money("debit_original", raw.debit_original)
        credit = _money("credit_original", raw.credit_original)
        if (debit > 0) == (credit > 0):
            raise _invalid(
                "MYBEE_CANDIDATE_LINES_INVALID", "one debit or credit is required"
            )
        source_ref = _scoped_id(
            "source_record_line_ref", raw.source_record_line_ref, 256
        )
        if source_ref in source_refs:
            raise _invalid(
                "MYBEE_CANDIDATE_LINES_INVALID", "source line references must be unique"
            )
        source_refs.add(source_ref)
        admitted.append(
            VoucherCandidateLine(
                account_id=_uuid("account_id", raw.account_id),
                debit_original=debit,
                credit_original=credit,
                source_record_line_ref=source_ref,
                description=(
                    _text("description", raw.description, 1000)
                    if raw.description is not None
                    else None
                ),
                evidence_hash=_hash_ref("evidence_hash", raw.evidence_hash),
            )
        )
    return tuple(admitted)


def _entity_ref(field: str, value: object, expected_type: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "id"}
        or value.get("type") != expected_type
    ):
        raise _invalid("MYBEE_CANDIDATE_RESULT_INVALID", f"{field} drifted")
    return {"type": expected_type, "id": _uuid(f"{field}.id", value["id"])}


def _admit_fx_evidence(value: Mapping[str, Any]) -> None:
    required = {
        "mode",
        "base_currency",
        "quote_currency",
        "normalized_rate",
        "desired_rate_date",
        "selected_rate_date",
        "staleness_business_days",
        "snapshot_hash",
        "policy_hash",
    }
    if set(value) != required or value["mode"] not in {
        "SAME_CURRENCY",
        "APPROVED_SNAPSHOT",
    }:
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "FX evidence drifted")
    _pattern("base_currency", value["base_currency"], _CURRENCY)
    _pattern("quote_currency", value["quote_currency"], _CURRENCY)
    _positive_decimal("normalized_rate", value["normalized_rate"])
    _date_text("desired_rate_date", value["desired_rate_date"])
    _date_text("selected_rate_date", value["selected_rate_date"])
    if (
        isinstance(value["staleness_business_days"], bool)
        or not isinstance(value["staleness_business_days"], int)
        or value["staleness_business_days"] < 0
    ):
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "FX staleness is invalid")
    if value["mode"] == "SAME_CURRENCY":
        if (
            value["base_currency"] != value["quote_currency"]
            or _positive_decimal("normalized_rate", value["normalized_rate"])
            != Decimal(1)
            or value["snapshot_hash"] is not None
            or value["policy_hash"] is not None
        ):
            raise _invalid(
                "MYBEE_CANDIDATE_VALIDATION_INVALID",
                "same-currency FX evidence drifted",
            )
    else:
        _hash_ref("snapshot_hash", value["snapshot_hash"])
        _hash_ref("policy_hash", value["policy_hash"])


def _admit_validation_line(value: object, *, expected_line_no: int) -> None:
    fields = {
        "line_no",
        "account_id",
        "debit_original",
        "credit_original",
        "debit_functional",
        "credit_functional",
        "functional_currency",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "line fields drifted")
    if value["line_no"] != expected_line_no:
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "line order drifted")
    _uuid("line.account_id", value["account_id"])
    debit_original = _money("line.debit_original", value["debit_original"])
    credit_original = _money("line.credit_original", value["credit_original"])
    debit_functional = _money("line.debit_functional", value["debit_functional"])
    credit_functional = _money("line.credit_functional", value["credit_functional"])
    _pattern("line.functional_currency", value["functional_currency"], _CURRENCY)
    if (debit_original > 0) == (credit_original > 0) or (debit_functional > 0) == (
        credit_functional > 0
    ):
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "line side is invalid")


def _admit_validation_totals(value: Mapping[str, Any]) -> None:
    fields = {
        "debit_original",
        "credit_original",
        "debit_functional",
        "credit_functional",
    }
    if set(value) != fields:
        raise _invalid("MYBEE_CANDIDATE_VALIDATION_INVALID", "totals drifted")
    amounts = {field: _money(field, value[field]) for field in fields}
    if (
        amounts["debit_original"] != amounts["credit_original"]
        or amounts["debit_functional"] != amounts["credit_functional"]
    ):
        raise _conflict(
            "MYBEE_CANDIDATE_VALIDATION_UNBALANCED", "provider totals are unbalanced"
        )


def _admit_review_event(value: object, *, candidate_id: str) -> None:
    fields = {
        "schema_version",
        "event_id",
        "candidate_id",
        "candidate_revision",
        "candidate_hash",
        "approval_case_id",
        "transition_kind",
        "from_state",
        "to_state",
        "expected_version",
        "resulting_version",
        "actor_subject_id",
        "reason",
        "validation_hash",
        "review_hash",
        "event_hash",
        "created_at",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid("MYBEE_CANDIDATE_REVIEW_INVALID", "event fields drifted")
    if (
        value["schema_version"] != "eos_candidate_review_event.v1"
        or value["candidate_id"] != candidate_id
        or value["transition_kind"] not in {"SUBMIT", "RETURN", "INVALIDATE"}
        or not _is_positive_int(value["candidate_revision"])
        or not _is_positive_int(value["expected_version"])
        or not _is_positive_int(value["resulting_version"])
        or value["resulting_version"] != value["expected_version"] + 1
    ):
        raise _conflict("MYBEE_CANDIDATE_REVIEW_BINDING_MISMATCH", "event drifted")
    _uuid("event_id", value["event_id"])
    _uuid("approval_case_id", value["approval_case_id"])
    _scoped_id("actor_subject_id", value["actor_subject_id"], 128)
    for field in ("candidate_hash", "review_hash", "event_hash"):
        _hash_ref(field, value[field])
    if value["validation_hash"] is not None:
        _hash_ref("validation_hash", value["validation_hash"])
    _timestamp("created_at", value["created_at"])


def _project_code(value: object, *, tenant_id: str) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if _PROJECT_CODE.fullmatch(normalized) is None or normalized[:4] != tenant_id:
        raise _invalid(
            "MYBEE_CANDIDATE_PROJECT_CODE_INVALID",
            "approved registration code required",
        )
    return normalized


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid("MYBEE_CANDIDATE_ID_INVALID", f"{field} must be a UUID") from exc


def _scoped_id(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if len(normalized) > maximum or _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(
            "MYBEE_CANDIDATE_ID_INVALID", f"{field} has invalid stable-reference syntax"
        )
    return normalized


def _text(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid("MYBEE_CANDIDATE_FIELD_INVALID", f"{field} is invalid")
    return normalized


def _pattern(field: str, value: object, pattern: re.Pattern[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if pattern.fullmatch(normalized) is None:
        raise _invalid("MYBEE_CANDIDATE_FIELD_INVALID", f"{field} is invalid")
    return normalized


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid("MYBEE_CANDIDATE_HASH_INVALID", f"{field} is invalid") from exc


def _money(field: str, value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid("MYBEE_CANDIDATE_AMOUNT_INVALID", f"{field} is invalid") from exc
    if (
        not amount.is_finite()
        or amount < 0
        or amount.as_tuple().exponent < -4
        or amount >= Decimal("1e16")
    ):
        raise _invalid("MYBEE_CANDIDATE_AMOUNT_INVALID", f"{field} is invalid")
    return amount.quantize(Decimal("0.0001"))


def _is_positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _date_text(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("MYBEE_CANDIDATE_DATE_INVALID", f"{field} is invalid")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise _invalid("MYBEE_CANDIDATE_DATE_INVALID", f"{field} is invalid") from exc


def _positive_decimal(field: str, value: object) -> Decimal:
    result = _money(field, value)
    if result <= 0:
        raise _invalid("MYBEE_CANDIDATE_AMOUNT_INVALID", f"{field} must be positive")
    return result


def _money_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")), "f")


def _timestamp(field: str, value: object) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _invalid(
                "MYBEE_CANDIDATE_TIME_INVALID", f"{field} is invalid"
            ) from exc
    else:
        raise _invalid("MYBEE_CANDIDATE_TIME_INVALID", f"{field} is invalid")
    if parsed.tzinfo is None:
        raise _invalid(
            "MYBEE_CANDIDATE_TIME_INVALID", f"{field} must include a timezone"
        )
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_object(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoucherCandidateConsumerError(
            "EOS_VOUCHER_CANDIDATE_RESPONSE_INVALID",
            "EOS returned a non-JSON response",
            status_code=502,
            retryable=True,
        ) from exc
    if not isinstance(value, dict):
        raise VoucherCandidateConsumerError(
            "EOS_VOUCHER_CANDIDATE_RESPONSE_INVALID",
            "EOS returned a non-object response",
            status_code=502,
            retryable=True,
        )
    return value


def _optional_json_object(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _invalid(code: str, detail: str) -> VoucherCandidateConsumerError:
    return VoucherCandidateConsumerError(code, detail, status_code=422)


def _conflict(code: str, detail: str) -> VoucherCandidateConsumerError:
    return VoucherCandidateConsumerError(code, detail, status_code=409)
