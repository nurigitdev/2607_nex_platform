"""Canonical EOS consumer for MyBee business-proposal approval journeys."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import canonical_json

from ..domain.documents import (
    GET_APPROVED_DOCUMENT_PATH,
    BusinessProposalForm,
    admit_approved_document_envelope,
    build_approved_document_request,
)
from .nex_approval_client import (
    EosScopedApprovalRequest,
    admit_scoped_approval_receipt,
    build_scoped_approval_request,
)


class BusinessApprovalConsumerError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = code
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class BusinessApprovalProviderRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    subject_id: str
    payload: Mapping[str, Any] | None = None


class BusinessApprovalProviderTransport(Protocol):
    def send(self, request: BusinessApprovalProviderRequest) -> Mapping[str, Any]: ...


class NexBusinessApprovalClient:
    """Submits via EOS; EOS remains the sole WC publication/final-proof owner."""

    def __init__(self, transport: BusinessApprovalProviderTransport) -> None:
        self._transport = transport

    def submit(
        self,
        proposal: BusinessProposalForm,
        *,
        business_operation_id: str,
        idempotency_key: str,
        case_id: str,
        approval_policy_id: str,
        correlation_id: str,
        causation_id: str,
        expires_at: datetime,
    ) -> Mapping[str, Any]:
        provider_request = build_business_proposal_approval_request(
            proposal,
            business_operation_id=business_operation_id,
            idempotency_key=idempotency_key,
            case_id=case_id,
            approval_policy_id=approval_policy_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            expires_at=expires_at,
        )
        response = self._transport.send(provider_request)
        receipt = admit_scoped_approval_receipt(
            response,
            tenant_id=proposal.tenant_id,
            business_operation_id=business_operation_id,
            case_id=case_id,
        )
        _require_case_binding(receipt, proposal)
        return receipt

    def create_draft(
        self,
        proposal: BusinessProposalForm,
        *,
        revision_id: str,
        transaction_type: str,
    ) -> Mapping[str, Any]:
        response = self._transport.send(
            BusinessApprovalProviderRequest(
                method="POST",
                path="/internal/v2/business-proposals",
                operation_id="BUSINESS.PROPOSAL.CREATE",
                tenant_id=proposal.tenant_id,
                subject_id=proposal.requester_subject_id,
                payload={
                    "proposal_id": proposal.proposal_id,
                    "revision_id": revision_id,
                    "company_id": proposal.company_id,
                    "document_type": proposal.document_type,
                    "work_code": proposal.work_code,
                    "title": proposal.title,
                    "purpose": proposal.purpose,
                    "business_justification": proposal.business_justification,
                    "transaction_type": transaction_type,
                    "requested_amount": _money_text(proposal.requested_amount),
                    "original_currency": proposal.currency,
                    "valid_from": _timestamp(proposal.valid_from),
                    "valid_until": (
                        _timestamp(proposal.valid_until)
                        if proposal.valid_until is not None
                        else None
                    ),
                    "scope_type": proposal.scope_type,
                    "project_ids": list(proposal.project_ids),
                    "project_codes": list(proposal.project_codes),
                    "attachment_manifest": [
                        {
                            "object_ref": item.object_ref,
                            "size": item.size_bytes,
                            "media_type": item.media_type,
                            "content_hash": item.content_hash,
                        }
                        for item in proposal.attachments
                    ],
                },
            )
        )
        return _admit_proposal_projection(
            response,
            proposal=proposal,
            expected_transaction_type=transaction_type,
            expected_states={"DRAFT"},
        )

    def get_proposal(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        proposal_id: str,
        expected_states: set[str] | frozenset[str],
    ) -> Mapping[str, Any]:
        response = self._transport.send(
            BusinessApprovalProviderRequest(
                method="GET",
                path=f"/internal/v2/business-proposals/{proposal_id}",
                operation_id="BUSINESS.PROPOSAL.GET",
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        )
        return _admit_proposal_projection(
            response,
            tenant_id=tenant_id,
            subject_id=subject_id,
            proposal_id=proposal_id,
            expected_states=expected_states,
        )

    def get_approved_document_for_proposal(
        self,
        *,
        proposal: Mapping[str, Any],
        envelope_id: str,
    ) -> Mapping[str, Any]:
        tenant_id = str(proposal.get("tenant_id") or "")
        subject_id = str(proposal.get("requester_subject_id") or "")
        proposal_id = str(proposal.get("proposal_id") or "")
        response = self._transport.send(
            BusinessApprovalProviderRequest(
                method="GET",
                path=GET_APPROVED_DOCUMENT_PATH.format(envelope_id=envelope_id),
                operation_id="BUSINESS.DOCUMENT_APPROVED.GET",
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        )
        envelope = admit_approved_document_envelope(
            response,
            tenant_id=tenant_id,
            envelope_id=envelope_id,
        )
        revision = proposal.get("current_revision")
        if not isinstance(revision, Mapping):
            raise BusinessApprovalConsumerError(
                "MYBEE_PROPOSAL_PROJECTION_INVALID",
                "EOS proposal projection lacks its submitted revision",
                status_code=502,
            )
        expected = {
            "approved_document_id": proposal_id,
            "document_revision": int(proposal.get("submitted_revision_no") or 0),
            "document_type": revision.get("document_type"),
            "work_code": revision.get("work_code"),
            "document_content_hash": revision.get("content_hash"),
            "attachment_manifest_hash": revision.get("attachment_manifest_hash"),
            "approved_amount": str(revision.get("requested_amount")),
            "approved_currency": revision.get("original_currency"),
        }
        if any(str(envelope.get(key)) != str(value) for key, value in expected.items()):
            raise BusinessApprovalConsumerError(
                "MYBEE_PROPOSAL_ENVELOPE_BINDING_MISMATCH",
                "EOS approved document does not bind the submitted proposal revision",
                status_code=409,
            )
        return envelope

    def get_approved_document(
        self,
        proposal: BusinessProposalForm,
        *,
        envelope_id: str,
    ) -> Mapping[str, Any]:
        request = build_approved_document_request(
            tenant_id=proposal.tenant_id,
            envelope_id=envelope_id,
            requester_subject_id=proposal.requester_subject_id,
        )
        response = self._transport.send(
            BusinessApprovalProviderRequest(
                method=request.method,
                path=request.path,
                operation_id=request.operation_id,
                tenant_id=request.tenant_id,
                subject_id=request.subject_id,
            )
        )
        envelope = admit_approved_document_envelope(
            response,
            tenant_id=proposal.tenant_id,
            envelope_id=envelope_id,
        )
        _require_envelope_binding(envelope, proposal)
        return envelope


class HttpBusinessApprovalProviderTransport:
    def __init__(
        self,
        *,
        eos_base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlparse(eos_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BusinessApprovalConsumerError(
                "MYBEE_APPROVAL_BASE_URL_INVALID",
                "EOS base URL must use http or https",
                status_code=422,
            )
        if not isinstance(service_token, str) or not service_token.strip():
            raise BusinessApprovalConsumerError(
                "MYBEE_APPROVAL_SERVICE_TOKEN_MISSING",
                "EOS service token is required",
                status_code=422,
            )
        if timeout_seconds <= 0:
            raise BusinessApprovalConsumerError(
                "MYBEE_APPROVAL_TIMEOUT_INVALID",
                "EOS timeout must be positive",
                status_code=422,
            )
        self._base_url = eos_base_url.rstrip("/") + "/"
        self._service_token = service_token.strip()
        self._timeout_seconds = float(timeout_seconds)

    def send(self, request: BusinessApprovalProviderRequest) -> Mapping[str, Any]:
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
            projection_not_ready = (
                exc.code == 404
                and request.operation_id == "BUSINESS.DOCUMENT_APPROVED.GET"
            )
            raise BusinessApprovalConsumerError(
                str(problem.get("error_code", "EOS_BUSINESS_APPROVAL_REJECTED")),
                "EOS rejected the business approval request",
                status_code=exc.code,
                retryable=(
                    projection_not_ready
                    or bool(problem.get("retryable", exc.code >= 500))
                ),
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise BusinessApprovalConsumerError(
                "EOS_BUSINESS_APPROVAL_UNAVAILABLE",
                "EOS business approval endpoint is unavailable",
                status_code=503,
                retryable=True,
            ) from exc


def build_business_proposal_approval_request(
    proposal: BusinessProposalForm,
    *,
    business_operation_id: str,
    idempotency_key: str,
    case_id: str,
    approval_policy_id: str,
    correlation_id: str,
    causation_id: str,
    expires_at: datetime,
) -> BusinessApprovalProviderRequest:
    request: EosScopedApprovalRequest = build_scoped_approval_request(
        tenant_id=proposal.tenant_id,
        business_operation_id=business_operation_id,
        idempotency_key=idempotency_key,
        case_id=case_id,
        company_id=proposal.company_id,
        purpose="DOCUMENT_SIGNOFF",
        scope_type=proposal.scope_type,
        project_ids=proposal.project_ids,
        subject_ref=proposal.subject_ref,
        subject_revision=proposal.revision,
        subject_hash=proposal.approval_subject_hash,
        requester_subject_id=proposal.requester_subject_id,
        approval_policy_id=approval_policy_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        document_signoff_context={
            "schema_version": "eos_document_signoff_context.v2",
            "envelope_id": str(
                uuid5(
                    NAMESPACE_URL,
                    "https://nex-platform.local/eos/document-signoff-envelope/"
                    f"{proposal.tenant_id}/{case_id}",
                )
            ),
            "approved_document_id": proposal.proposal_id,
            "document_revision": proposal.revision,
            "document_type": proposal.document_type,
            "work_code": proposal.work_code,
            "document_content_hash": proposal.document_content_hash,
            "attachment_manifest_hash": proposal.attachment_manifest_hash,
            "approved_amount": _money_text(proposal.requested_amount),
            "approved_currency": proposal.currency,
            "tolerance_policy_hash": None,
            "valid_from": _timestamp(proposal.valid_from),
            "valid_until": (
                _timestamp(proposal.valid_until)
                if proposal.valid_until is not None
                else None
            ),
            "subject_hash": proposal.approval_subject_hash,
            "allowed_project_codes": list(proposal.project_codes),
        },
        expires_at=expires_at,
    )
    return BusinessApprovalProviderRequest(
        method=request.method,
        path=request.path,
        operation_id=request.operation_id,
        tenant_id=proposal.tenant_id,
        subject_id=proposal.requester_subject_id,
        payload=request.payload,
    )


def _require_case_binding(
    receipt: Mapping[str, Any], proposal: BusinessProposalForm
) -> None:
    case = receipt["scoped_approval_case"]
    expected = {
        "company_id": proposal.company_id,
        "purpose": "DOCUMENT_SIGNOFF",
        "scope_type": proposal.scope_type,
        "project_ids": list(proposal.project_ids),
        "subject_ref": proposal.subject_ref,
        "subject_revision": proposal.revision,
        "subject_hash": proposal.approval_subject_hash,
    }
    if any(case.get(field) != value for field, value in expected.items()):
        raise BusinessApprovalConsumerError(
            "MYBEE_PROPOSAL_APPROVAL_BINDING_MISMATCH",
            "EOS approval receipt does not bind the exact proposal revision",
            status_code=409,
        )


def _require_envelope_binding(
    envelope: Mapping[str, Any], proposal: BusinessProposalForm
) -> None:
    expected = {
        "company_id": proposal.company_id,
        "approved_document_id": proposal.proposal_id,
        "document_revision": proposal.revision,
        "document_type": proposal.document_type,
        "work_code": proposal.work_code,
        "document_content_hash": proposal.document_content_hash,
        "attachment_manifest_hash": proposal.attachment_manifest_hash,
        "scope_type": proposal.scope_type,
        "allowed_project_ids": list(proposal.project_ids),
        "allowed_project_codes": list(proposal.project_codes),
        "approved_amount": _money_text(proposal.requested_amount),
        "approved_currency": proposal.currency,
        "valid_from": _timestamp(proposal.valid_from),
        "valid_until": (
            _timestamp(proposal.valid_until)
            if proposal.valid_until is not None
            else None
        ),
        "state": "ACTIVE",
        "usable": True,
    }
    if any(envelope.get(field) != value for field, value in expected.items()):
        raise BusinessApprovalConsumerError(
            "MYBEE_PROPOSAL_ENVELOPE_BINDING_MISMATCH",
            "EOS approved document does not bind the exact proposal revision",
            status_code=409,
        )


def _admit_proposal_projection(
    value: object,
    *,
    expected_states: set[str] | frozenset[str],
    proposal: BusinessProposalForm | None = None,
    expected_transaction_type: str | None = None,
    tenant_id: str | None = None,
    subject_id: str | None = None,
    proposal_id: str | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BusinessApprovalConsumerError(
            "MYBEE_PROPOSAL_PROJECTION_INVALID",
            "EOS returned an invalid proposal projection",
            status_code=502,
            retryable=True,
        )
    result = dict(value)
    expected_tenant = proposal.tenant_id if proposal is not None else str(tenant_id or "")
    expected_subject = (
        proposal.requester_subject_id if proposal is not None else str(subject_id or "")
    )
    expected_proposal = (
        proposal.proposal_id if proposal is not None else str(proposal_id or "")
    )
    revision = result.get("current_revision")
    if (
        result.get("tenant_id") != expected_tenant
        or result.get("requester_subject_id") != expected_subject
        or result.get("proposal_id") != expected_proposal
        or result.get("state") not in expected_states
        or not isinstance(revision, Mapping)
        or int(result.get("current_revision_no") or 0) <= 0
        or int(result.get("version") or 0) <= 0
    ):
        raise BusinessApprovalConsumerError(
            "MYBEE_PROPOSAL_PROJECTION_BINDING_MISMATCH",
            "EOS proposal projection differs from the requested owner scope",
            status_code=409,
        )
    if proposal is not None:
        expected = {
            "document_type": proposal.document_type,
            "work_code": proposal.work_code,
            "title": proposal.title,
            "purpose": proposal.purpose,
            "business_justification": proposal.business_justification,
            "transaction_type": expected_transaction_type,
            "requested_amount": _money_text(proposal.requested_amount),
            "original_currency": proposal.currency,
            "valid_from": _timestamp(proposal.valid_from),
            "valid_until": (
                _timestamp(proposal.valid_until)
                if proposal.valid_until is not None
                else None
            ),
            "scope_type": proposal.scope_type,
            "project_ids": sorted(proposal.project_ids),
            "project_codes": sorted(proposal.project_codes),
            "attachment_manifest": [
                {
                    "object_ref": item.object_ref,
                    "size": item.size_bytes,
                    "media_type": item.media_type,
                    "content_hash": item.content_hash,
                }
                for item in proposal.attachments
            ],
        }
        timestamp_fields = {"valid_from", "valid_until"}
        scalar_drifted = any(
            revision.get(field) != expected_value
            for field, expected_value in expected.items()
            if field not in timestamp_fields
        )
        timestamp_drifted = any(
            not _same_instant(revision.get(field), expected[field])
            for field in timestamp_fields
        )
        if (
            scalar_drifted
            or timestamp_drifted
            or not str(revision.get("content_hash") or "").startswith("sha256:")
        ):
            raise BusinessApprovalConsumerError(
                "MYBEE_PROPOSAL_DRAFT_BINDING_MISMATCH",
                "EOS proposal draft differs from the submitted draft",
                status_code=409,
            )
    return result


def _money_text(value: object) -> str:
    from decimal import Decimal

    return format(Decimal(str(value)).quantize(Decimal("0.0001")), "f")


def _same_instant(actual: object, expected: object) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if not isinstance(actual, str) or not isinstance(expected, str):
        return False
    try:
        actual_at = datetime.fromisoformat(actual.replace("Z", "+00:00"))
        expected_at = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    except ValueError:
        return False
    if actual_at.utcoffset() is None or expected_at.utcoffset() is None:
        return False
    return actual_at.astimezone(UTC) == expected_at.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _json_object(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BusinessApprovalConsumerError(
            "EOS_BUSINESS_APPROVAL_RESPONSE_INVALID",
            "EOS returned a non-JSON approval response",
            status_code=502,
            retryable=True,
        ) from exc
    if not isinstance(value, Mapping):
        raise BusinessApprovalConsumerError(
            "EOS_BUSINESS_APPROVAL_RESPONSE_INVALID",
            "EOS returned a non-object approval response",
            status_code=502,
            retryable=True,
        )
    return dict(value)


def _optional_json_object(raw: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}
