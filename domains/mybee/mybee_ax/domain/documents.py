"""MyBee business-proposal form and immutable EOS document consumer contract."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

GET_APPROVED_DOCUMENT_OPERATION = "BUSINESS.DOCUMENT_APPROVED.GET"
GET_APPROVED_DOCUMENT_PATH = "/internal/v2/finance/approved-documents/{envelope_id}"
APPROVED_DOCUMENT_STATES = frozenset({"ACTIVE", "REVOKED", "EXPIRED", "SUPERSEDED"})
APPROVED_DOCUMENT_SCOPES = frozenset({"COMPANY", "PROJECT", "PROJECT_SET"})
BUSINESS_PROPOSAL_TEMPLATE_SCHEMA = "nex.mybee.business-proposal-template.v1"
BUSINESS_PROPOSAL_SCHEMA = "nex.mybee.business-proposal.v1"
BUSINESS_PROPOSAL_TEMPLATE_ID = "mybee.d04.business-proposal"
BUSINESS_PROPOSAL_TEMPLATE_VERSION = "1.0.0"
BUSINESS_PROPOSAL_TEMPLATE_STATUS = "EOS_CONSUMER_ADMITTED"
BUSINESS_PROPOSAL_DOCUMENT_TYPE = "BUSINESS_PROPOSAL"
BUSINESS_PROPOSAL_WORK_CODE = "FL0004011"
DEFAULT_BUSINESS_PROPOSAL_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "templates/d04/business_proposal.v1.json"
)
_BUSINESS_PROPOSAL_REQUIRED_FIELDS = (
    "proposal_id",
    "revision",
    "company_id",
    "title",
    "purpose",
    "business_justification",
    "scope_type",
    "project_ids",
    "requested_amount",
    "currency",
    "requester_subject_id",
    "valid_from",
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "envelope_id",
        "company_id",
        "approved_document_id",
        "document_revision",
        "document_type",
        "work_code",
        "document_content_hash",
        "attachment_manifest_hash",
        "business_approval_proof_id",
        "business_proof_hash",
        "approval_policy_id",
        "approval_policy_version",
        "approval_policy_hash",
        "scope_type",
        "project_set_hash",
        "allowed_project_ids",
        "approved_amount",
        "approved_currency",
        "remaining_amount",
        "tolerance_policy_hash",
        "valid_from",
        "valid_until",
        "state",
        "usable",
        "approved_at",
        "approved_by_principal_ref",
        "source_work_item_ref",
        "payload_hash",
        "created_business_operation_id",
        "created_at",
    }
)


class ApprovedDocumentContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


class BusinessProposalContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class BusinessProposalAttachment:
    object_ref: str
    file_name: str
    media_type: str
    size_bytes: int
    content_hash: str


@dataclass(frozen=True)
class BusinessProposalForm:
    tenant_id: str
    proposal_id: str
    revision: int
    company_id: str
    title: str
    purpose: str
    business_justification: str
    scope_type: str
    project_ids: tuple[str, ...]
    requested_amount: Decimal
    currency: str
    requester_subject_id: str
    valid_from: datetime
    valid_until: datetime | None
    attachments: tuple[BusinessProposalAttachment, ...]
    template_id: str = BUSINESS_PROPOSAL_TEMPLATE_ID
    template_version: str = BUSINESS_PROPOSAL_TEMPLATE_VERSION
    document_type: str = BUSINESS_PROPOSAL_DOCUMENT_TYPE
    work_code: str = BUSINESS_PROPOSAL_WORK_CODE

    @property
    def subject_ref(self) -> str:
        return f"mybee.business-proposal:{self.proposal_id}:revision:{self.revision}"

    @property
    def document_content_hash(self) -> str:
        return semantic_sha256_hash_ref(self.document_content())

    @property
    def attachment_manifest_hash(self) -> str:
        return semantic_sha256_hash_ref(self.attachment_manifest())

    @property
    def approval_subject_hash(self) -> str:
        return semantic_sha256_hash_ref(
            {
                "schema_version": "nex.mybee.business-proposal-approval.v1",
                "tenant_id": self.tenant_id,
                "proposal_id": self.proposal_id,
                "revision": self.revision,
                "company_id": self.company_id,
                "scope_type": self.scope_type,
                "project_ids": list(self.project_ids),
                "requested_amount": _decimal_text(self.requested_amount),
                "currency": self.currency,
                "document_content_hash": self.document_content_hash,
                "attachment_manifest_hash": self.attachment_manifest_hash,
                "valid_from": _datetime_text(self.valid_from),
                "valid_until": (
                    _datetime_text(self.valid_until)
                    if self.valid_until is not None
                    else None
                ),
            }
        )

    def document_content(self) -> Mapping[str, Any]:
        return {
            "schema_version": BUSINESS_PROPOSAL_SCHEMA,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "proposal_id": self.proposal_id,
            "revision": self.revision,
            "company_id": self.company_id,
            "document_type": self.document_type,
            "work_code": self.work_code,
            "title": self.title,
            "purpose": self.purpose,
            "business_justification": self.business_justification,
            "scope_type": self.scope_type,
            "project_ids": list(self.project_ids),
            "requested_amount": _decimal_text(self.requested_amount),
            "currency": self.currency,
            "requester_subject_id": self.requester_subject_id,
            "valid_from": _datetime_text(self.valid_from),
            "valid_until": (
                _datetime_text(self.valid_until)
                if self.valid_until is not None
                else None
            ),
        }

    def attachment_manifest(self) -> Mapping[str, Any]:
        return {
            "schema_version": "nex.mybee.business-proposal-attachments.v1",
            "proposal_id": self.proposal_id,
            "revision": self.revision,
            "attachments": [
                {
                    "object_ref": item.object_ref,
                    "file_name": item.file_name,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "content_hash": item.content_hash,
                }
                for item in self.attachments
            ],
        }


def build_business_proposal_form(
    *,
    tenant_id: str,
    proposal_id: str,
    revision: int,
    company_id: str,
    title: str,
    purpose: str,
    business_justification: str,
    scope_type: str,
    project_ids: Sequence[str],
    requested_amount: Decimal,
    currency: str,
    requester_subject_id: str,
    valid_from: datetime,
    valid_until: datetime | None = None,
    attachments: Sequence[BusinessProposalAttachment] = (),
) -> BusinessProposalForm:
    admitted_scope = _proposal_choice(
        "scope_type", scope_type, APPROVED_DOCUMENT_SCOPES
    )
    admitted_projects = _proposal_projects(project_ids)
    if (
        (admitted_scope == "COMPANY" and admitted_projects)
        or (admitted_scope == "PROJECT" and len(admitted_projects) != 1)
        or (admitted_scope == "PROJECT_SET" and len(admitted_projects) < 2)
    ):
        raise _proposal_error(
            "MYBEE_PROPOSAL_SCOPE_INVALID",
            "scope type and Project set do not agree",
        )
    admitted_valid_from = _proposal_datetime("valid_from", valid_from)
    admitted_valid_until = (
        _proposal_datetime("valid_until", valid_until)
        if valid_until is not None
        else None
    )
    if admitted_valid_until is not None and admitted_valid_until <= admitted_valid_from:
        raise _proposal_error(
            "MYBEE_PROPOSAL_PERIOD_INVALID", "valid_until must follow valid_from"
        )
    admitted_attachments = _proposal_attachments(attachments)
    return BusinessProposalForm(
        tenant_id=_proposal_scoped_id("tenant_id", tenant_id, 128),
        proposal_id=_proposal_scoped_id("proposal_id", proposal_id, 128),
        revision=_proposal_positive_int("revision", revision),
        company_id=_proposal_uuid("company_id", company_id),
        title=_proposal_text("title", title, 200),
        purpose=_proposal_text("purpose", purpose, 2000),
        business_justification=_proposal_text(
            "business_justification", business_justification, 4000
        ),
        scope_type=admitted_scope,
        project_ids=admitted_projects,
        requested_amount=_proposal_positive_decimal(
            "requested_amount", requested_amount
        ),
        currency=_proposal_currency("currency", currency),
        requester_subject_id=_proposal_scoped_id(
            "requester_subject_id", requester_subject_id, 128
        ),
        valid_from=admitted_valid_from,
        valid_until=admitted_valid_until,
        attachments=admitted_attachments,
    )


def calculate_business_proposal_template_digest(value: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "template_digest"}
    )


def load_business_proposal_template(
    path: Path = DEFAULT_BUSINESS_PROPOSAL_TEMPLATE_PATH,
) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_UNREADABLE", "template cannot be loaded"
        ) from exc
    if not isinstance(value, Mapping):
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_INVALID", "template must be an object"
        )
    expected_fields = {
        "schema_version",
        "template_id",
        "template_version",
        "revision",
        "status",
        "document_type",
        "work_code",
        "required_fields",
        "attachment_contract",
        "provider_contract",
        "runtime_boundaries",
        "template_digest",
    }
    if set(value) != expected_fields:
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_INVALID", "template fields drifted"
        )
    expected_identity = (
        BUSINESS_PROPOSAL_TEMPLATE_SCHEMA,
        BUSINESS_PROPOSAL_TEMPLATE_ID,
        BUSINESS_PROPOSAL_TEMPLATE_VERSION,
        1,
        BUSINESS_PROPOSAL_TEMPLATE_STATUS,
        BUSINESS_PROPOSAL_DOCUMENT_TYPE,
        BUSINESS_PROPOSAL_WORK_CODE,
    )
    actual_identity = tuple(
        value[field]
        for field in (
            "schema_version",
            "template_id",
            "template_version",
            "revision",
            "status",
            "document_type",
            "work_code",
        )
    )
    if actual_identity != expected_identity:
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_INVALID", "template identity drifted"
        )
    if value["required_fields"] != list(_BUSINESS_PROPOSAL_REQUIRED_FIELDS):
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_INVALID", "required fields drifted"
        )
    provider = value["provider_contract"]
    boundaries = value["runtime_boundaries"]
    attachment = value["attachment_contract"]
    if not isinstance(provider, Mapping) or provider != {
        "approval_operation": "FINANCE.ACCOUNTING_APPROVAL.REQUEST",
        "approval_purpose": "DOCUMENT_SIGNOFF",
        "approved_document_operation": GET_APPROVED_DOCUMENT_OPERATION,
        "provider": "nex-eos",
        "workflow_owner": "nex-wc",
    }:
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_INVALID", "provider contract drifted"
        )
    if not isinstance(boundaries, Mapping) or any(
        boundaries.get(field) is not expected
        for field, expected in {
            "direct_database_access": False,
            "direct_wc_submission": False,
            "service_private_imports": False,
            "approved_document_creation_owned_by_eos": True,
        }.items()
    ):
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_INVALID", "runtime boundary drifted"
        )
    if not isinstance(attachment, Mapping) or attachment != {
        "multiple": True,
        "manifest_hash_required": True,
        "content_hash_required": True,
        "object_ref_only": True,
    }:
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_INVALID", "attachment contract drifted"
        )
    if value["template_digest"] != calculate_business_proposal_template_digest(value):
        raise _proposal_error(
            "MYBEE_PROPOSAL_TEMPLATE_HASH_MISMATCH", "template digest drifted"
        )
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class EosApprovedDocumentRequest:
    method: str
    path: str
    operation_id: str
    tenant_id: str
    subject_id: str


def build_approved_document_request(
    *, tenant_id: str, envelope_id: str, requester_subject_id: str
) -> EosApprovedDocumentRequest:
    return EosApprovedDocumentRequest(
        method="GET",
        path=GET_APPROVED_DOCUMENT_PATH.format(
            envelope_id=_uuid("envelope_id", envelope_id)
        ),
        operation_id=GET_APPROVED_DOCUMENT_OPERATION,
        tenant_id=_scoped_id("tenant_id", tenant_id, 128),
        subject_id=_scoped_id("requester_subject_id", requester_subject_id, 128),
    )


def admit_approved_document_envelope(
    value: object, *, tenant_id: str, envelope_id: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise _error("EOS_APPROVED_DOCUMENT_FIELDS_INVALID", "fields drifted")
    item = dict(value)
    if item["schema_version"] != "eos_approved_document_envelope.v1":
        raise _error("EOS_APPROVED_DOCUMENT_SCHEMA_INVALID", "version drifted")
    if item["tenant_id"] != _scoped_id("tenant_id", tenant_id, 128):
        raise _error("EOS_APPROVED_DOCUMENT_SCOPE_MISMATCH", "tenant drifted")
    if item["envelope_id"] != _uuid("envelope_id", envelope_id):
        raise _error("EOS_APPROVED_DOCUMENT_SCOPE_MISMATCH", "envelope drifted")
    for field in (
        "company_id",
        "business_approval_proof_id",
        "approval_policy_id",
        "created_business_operation_id",
    ):
        _uuid(field, item[field])
    _scoped_id("approved_document_id", item["approved_document_id"], 128)
    _positive_int("document_revision", item["document_revision"])
    _scoped_id("document_type", item["document_type"], 64)
    if not isinstance(item["work_code"], str) or not _WORK_CODE.fullmatch(
        item["work_code"]
    ):
        raise _error("EOS_APPROVED_DOCUMENT_WORK_CODE_INVALID", "work code drifted")
    for field in (
        "document_content_hash",
        "attachment_manifest_hash",
        "business_proof_hash",
        "approval_policy_hash",
        "project_set_hash",
        "payload_hash",
    ):
        _hash_ref(field, item[field])
    if item["tolerance_policy_hash"] is not None:
        _hash_ref("tolerance_policy_hash", item["tolerance_policy_hash"])
    _positive_int("approval_policy_version", item["approval_policy_version"])
    scope_type = _choice("scope_type", item["scope_type"], APPROVED_DOCUMENT_SCOPES)
    project_ids = item["allowed_project_ids"]
    if not isinstance(project_ids, list) or project_ids != sorted(set(project_ids)):
        raise _error(
            "EOS_APPROVED_DOCUMENT_PROJECT_SET_INVALID",
            "Project IDs must be sorted and unique",
        )
    for project_id in project_ids:
        _uuid("allowed_project_ids", project_id)
    if (
        (scope_type == "COMPANY" and project_ids)
        or (scope_type == "PROJECT" and len(project_ids) != 1)
        or (scope_type == "PROJECT_SET" and len(project_ids) < 2)
    ):
        raise _error("EOS_APPROVED_DOCUMENT_PROJECT_SET_INVALID", "scope shape drifted")
    approved = _decimal("approved_amount", item["approved_amount"])
    remaining = _decimal("remaining_amount", item["remaining_amount"])
    if remaining < 0 or remaining > approved:
        raise _error(
            "EOS_APPROVED_DOCUMENT_ALLOWANCE_INVALID", "remaining amount drifted"
        )
    if not isinstance(item["approved_currency"], str) or not _CURRENCY.fullmatch(
        item["approved_currency"]
    ):
        raise _error("EOS_APPROVED_DOCUMENT_CURRENCY_INVALID", "currency drifted")
    state = _choice("state", item["state"], APPROVED_DOCUMENT_STATES)
    if not isinstance(item["usable"], bool) or (item["usable"] and state != "ACTIVE"):
        raise _error("EOS_APPROVED_DOCUMENT_USABILITY_INVALID", "usability drifted")
    valid_from = _timestamp("valid_from", item["valid_from"])
    valid_until = (
        _timestamp("valid_until", item["valid_until"])
        if item["valid_until"] is not None
        else None
    )
    if valid_until is not None and valid_until <= valid_from:
        raise _error("EOS_APPROVED_DOCUMENT_PERIOD_INVALID", "period reversed")
    _timestamp("approved_at", item["approved_at"])
    _timestamp("created_at", item["created_at"])
    principal = item["approved_by_principal_ref"]
    if not isinstance(principal, Mapping) or set(principal) != {"type", "id"}:
        raise _error("EOS_APPROVED_DOCUMENT_PRINCIPAL_INVALID", "principal drifted")
    _scoped_id("approved_by_principal_ref.type", principal["type"], 32)
    _scoped_id("approved_by_principal_ref.id", principal["id"], 128)
    _scoped_id("source_work_item_ref", item["source_work_item_ref"], 256)
    return MappingProxyType(item)


def _scoped_id(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or not _SCOPED_ID.fullmatch(value)
    ):
        raise _error("EOS_APPROVED_DOCUMENT_ID_INVALID", f"{field} invalid")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _error("EOS_APPROVED_DOCUMENT_ID_INVALID", f"{field} invalid") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error("EOS_APPROVED_DOCUMENT_NUMBER_INVALID", f"{field} invalid")
    return value


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _error("EOS_APPROVED_DOCUMENT_HASH_INVALID", f"{field} invalid") from exc


def _choice(field: str, value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _error("EOS_APPROVED_DOCUMENT_ENUM_INVALID", f"{field} invalid")
    return value


def _decimal(field: str, value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _error(
            "EOS_APPROVED_DOCUMENT_AMOUNT_INVALID", f"{field} invalid"
        ) from exc
    if not result.is_finite() or result < 0 or result.as_tuple().exponent < -4:
        raise _error("EOS_APPROVED_DOCUMENT_AMOUNT_INVALID", f"{field} invalid")
    return result


def _timestamp(field: str, value: object) -> datetime:
    if not isinstance(value, str):
        raise _error("EOS_APPROVED_DOCUMENT_TIME_INVALID", f"{field} invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error("EOS_APPROVED_DOCUMENT_TIME_INVALID", f"{field} invalid") from exc
    if parsed.tzinfo is None:
        raise _error("EOS_APPROVED_DOCUMENT_TIME_INVALID", f"{field} invalid")
    return parsed


def _proposal_scoped_id(field: str, value: object, maximum: int) -> str:
    try:
        return _scoped_id(field, value, maximum)
    except ApprovedDocumentContractError as exc:
        raise _proposal_error(
            "MYBEE_PROPOSAL_ID_INVALID", f"{field} invalid"
        ) from exc


def _proposal_uuid(field: str, value: object) -> str:
    try:
        return _uuid(field, value)
    except ApprovedDocumentContractError as exc:
        raise _proposal_error(
            "MYBEE_PROPOSAL_ID_INVALID", f"{field} invalid"
        ) from exc


def _proposal_positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _proposal_error(
            "MYBEE_PROPOSAL_FIELD_INVALID", f"{field} invalid"
        )
    return value


def _proposal_text(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
    ):
        raise _proposal_error(
            "MYBEE_PROPOSAL_FIELD_INVALID", f"{field} invalid"
        )
    return value


def _proposal_choice(field: str, value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise _proposal_error(
            "MYBEE_PROPOSAL_FIELD_INVALID", f"{field} invalid"
        )
    return value


def _proposal_projects(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _proposal_error(
            "MYBEE_PROPOSAL_SCOPE_INVALID", "project_ids must be an array"
        )
    admitted = tuple(sorted(_proposal_uuid("project_ids", item) for item in value))
    if len(admitted) != len(set(admitted)):
        raise _proposal_error(
            "MYBEE_PROPOSAL_SCOPE_INVALID", "project_ids must be unique"
        )
    return admitted


def _proposal_positive_decimal(field: str, value: object) -> Decimal:
    try:
        admitted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _proposal_error(
            "MYBEE_PROPOSAL_AMOUNT_INVALID", f"{field} invalid"
        ) from exc
    if not admitted.is_finite() or admitted <= 0 or admitted.as_tuple().exponent < -4:
        raise _proposal_error(
            "MYBEE_PROPOSAL_AMOUNT_INVALID", f"{field} invalid"
        )
    try:
        return admitted.quantize(Decimal("0.0001"))
    except InvalidOperation as exc:
        raise _proposal_error(
            "MYBEE_PROPOSAL_AMOUNT_INVALID", f"{field} invalid"
        ) from exc


def _proposal_currency(field: str, value: object) -> str:
    if not isinstance(value, str) or not _CURRENCY.fullmatch(value):
        raise _proposal_error(
            "MYBEE_PROPOSAL_CURRENCY_INVALID", f"{field} invalid"
        )
    return value


def _proposal_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _proposal_error(
            "MYBEE_PROPOSAL_TIME_INVALID", f"{field} invalid"
        )
    return value.astimezone(UTC)


def _proposal_attachments(
    value: object,
) -> tuple[BusinessProposalAttachment, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _proposal_error(
            "MYBEE_PROPOSAL_ATTACHMENT_INVALID", "attachments must be an array"
        )
    admitted: list[BusinessProposalAttachment] = []
    for item in value:
        if not isinstance(item, BusinessProposalAttachment):
            raise _proposal_error(
                "MYBEE_PROPOSAL_ATTACHMENT_INVALID",
                "attachment must use BusinessProposalAttachment",
            )
        if (
            isinstance(item.size_bytes, bool)
            or not isinstance(item.size_bytes, int)
            or item.size_bytes < 1
        ):
            raise _proposal_error(
                "MYBEE_PROPOSAL_ATTACHMENT_INVALID", "size_bytes invalid"
            )
        try:
            content_hash = validate_hash_ref(item.content_hash)
        except (TypeError, ValueError) as exc:
            raise _proposal_error(
                "MYBEE_PROPOSAL_ATTACHMENT_INVALID", "content_hash invalid"
            ) from exc
        admitted.append(
            BusinessProposalAttachment(
                object_ref=_proposal_text("object_ref", item.object_ref, 512),
                file_name=_proposal_text("file_name", item.file_name, 255),
                media_type=_proposal_text("media_type", item.media_type, 128),
                size_bytes=item.size_bytes,
                content_hash=content_hash,
            )
        )
    admitted.sort(key=lambda item: item.object_ref)
    if len({item.object_ref for item in admitted}) != len(admitted):
        raise _proposal_error(
            "MYBEE_PROPOSAL_ATTACHMENT_INVALID", "object_ref must be unique"
        )
    return tuple(admitted)


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")), "f")


def _datetime_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _error(code: str, detail: str) -> ApprovedDocumentContractError:
    return ApprovedDocumentContractError(code, detail)


def _proposal_error(code: str, detail: str) -> BusinessProposalContractError:
    return BusinessProposalContractError(code, detail)
