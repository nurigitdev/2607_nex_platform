from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref
from sqlalchemy.orm import Session

from .attachments import (
    EosAttachmentError,
    SqlAlchemyEosAttachmentRepository,
    VoucherAttachmentInput,
)
from .authorization import (
    EosAuthorizationError,
    EosAuthorizationTarget,
    EosVoucherAuthorizationClient,
)
from .business_transactions import (
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .vouchers import (
    EosVoucherError,
    SqlAlchemyEosVoucherRepository,
    VoucherDraftInput,
    VoucherLineInput,
)
from .voucher_access import EosVoucherAccessError, EosVoucherAccessService

EOS_CREATE_VOUCHER_OPERATION = "FINANCE.CREATE_VOUCHER_DRAFT"
EOS_CREATE_VOUCHER_SCHEMA = "eos_create_voucher_draft_command.v1"
EOS_CREATE_VOUCHER_RESULT_SCHEMA = "eos_create_voucher_draft_result.v1"
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_MONEY = re.compile(r"^-?(?:0|[1-9][0-9]{0,17})\.[0-9]{2}$")


class EosVoucherCommandError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class EosServiceCaller:
    subject: str
    audience: str
    scopes: Sequence[str]


@dataclass(frozen=True)
class ParsedVoucherDraftCommand:
    tenant_id: str
    business_operation_id: str
    idempotency_key: str
    payload_hash: str
    requester_ref: dict[str, str]
    project_ref: dict[str, str]
    voucher_type: str
    transaction_date: date
    currency: str
    description: str
    lines: tuple[VoucherLineInput, ...]
    nsl_approval_request_id: str
    nsl_approval_evidence_ref: str
    business_approval_proof_ref: str | None
    attachment_batch_id: str | None
    attachment_manifest_hash: str | None
    attachments: tuple[VoucherAttachmentInput, ...]
    trace: dict[str, str]

    def business_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": EOS_CREATE_VOUCHER_SCHEMA,
            "tenant_id": self.tenant_id,
            "requester_ref": dict(self.requester_ref),
            "project_ref": dict(self.project_ref),
            "voucher_type": self.voucher_type,
            "transaction_date": self.transaction_date.isoformat(),
            "currency": self.currency,
            "description_text": self.description,
            "lines": [
                {
                    "line_no": line_no,
                    "account_ref": {
                        "type": "eos.account",
                        "id": line.account_id,
                    },
                    "signed_amount": format(line.signed_amount, ".2f"),
                    "economic_category": line.economic_category,
                    "description": line.description,
                    "evidence_refs": list(line.evidence_refs),
                }
                for line_no, line in enumerate(self.lines, start=1)
            ],
            "attachments": [
                {
                    "attachment_id": item.attachment_id,
                    "object_ref": item.object_ref,
                    "display_name": item.display_name,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "content_sha256": item.content_sha256,
                    "evidence_ref": item.evidence_ref,
                }
                for item in self.attachments
            ],
        }
        if self.attachment_batch_id is not None:
            payload.update(
                {
                    "attachment_batch_id": self.attachment_batch_id,
                    "attachment_manifest_hash": self.attachment_manifest_hash,
                }
            )
        return payload


class EosCreateVoucherDraftService:
    def __init__(
        self,
        *,
        coordinator: EosBusinessTransactionCoordinator,
        vouchers: SqlAlchemyEosVoucherRepository,
        authorizer: EosVoucherAuthorizationClient,
        project_access: EosVoucherAccessService | None = None,
        attachments: SqlAlchemyEosAttachmentRepository | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._vouchers = vouchers
        self._authorizer = authorizer
        self._project_access = project_access
        self._attachments = attachments
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self, payload: Mapping[str, Any], *, caller: EosServiceCaller
    ) -> dict[str, Any]:
        command = parse_create_voucher_draft_command(payload)
        computed_hash = nsl_write_payload_hash_ref(command.business_payload())
        if computed_hash != command.payload_hash:
            raise EosVoucherCommandError(
                "EOS_VOUCHER_PAYLOAD_HASH_MISMATCH",
                "Canonical Voucher payload hash does not match the supplied hash.",
                status_code=422,
            )
        try:
            evidence = self._authorizer.authorize_create(
                EosAuthorizationTarget(
                    tenant_id=command.tenant_id,
                    subject_id=command.requester_ref["id"],
                    service_subject=caller.subject,
                    service_audience=caller.audience,
                    service_scopes=caller.scopes,
                    project_id=command.project_ref["id"],
                    resource_type="voucher_draft",
                    resource_id=command.business_operation_id,
                )
            )
        except EosAuthorizationError as exc:
            raise EosVoucherCommandError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc

        voucher_id = _uuid("voucher_id", self._id_factory())
        committed_at = _aware_time(self._clock())

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise EosBusinessOperationError(
                    "EOS_VOUCHER_TRANSACTION_REQUIRED",
                    "Voucher command requires a database transaction.",
                    status_code=500,
                )
            try:
                if self._project_access is not None:
                    self._project_access.require_create_membership(
                        session,
                        tenant_id=command.tenant_id,
                        project_id=command.project_ref["id"],
                        subject_id=command.requester_ref["id"],
                    )
                self._vouchers.create_draft_in_session(
                    session,
                    VoucherDraftInput(
                        tenant_id=command.tenant_id,
                        voucher_id=voucher_id,
                        project_id=command.project_ref["id"],
                        transaction_date=command.transaction_date,
                        description=command.description,
                        requester_ref=command.requester_ref,
                        source_ref={
                            "type": "nsl.approval_request",
                            "id": command.nsl_approval_request_id,
                        },
                        lines=command.lines,
                        attachment_batch_id=command.attachment_batch_id,
                        attachment_manifest_hash=command.attachment_manifest_hash,
                        voucher_type=command.voucher_type,
                        currency=command.currency,
                    ),
                )
                if command.attachments:
                    if self._attachments is None:
                        raise EosBusinessOperationError(
                            "EOS_ATTACHMENT_RESOLVER_NOT_CONFIGURED",
                            "Voucher attachment resolver is not configured.",
                            status_code=503,
                            retryable=True,
                        )
                    self._attachments.attach_many_in_session(
                        session,
                        tenant_id=command.tenant_id,
                        voucher_id=voucher_id,
                        attachments=command.attachments,
                        attachment_batch_id=command.attachment_batch_id,
                        attachment_manifest_hash=command.attachment_manifest_hash,
                    )
            except (EosVoucherError, EosAttachmentError, EosVoucherAccessError) as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                ) from exc
            return {
                "business_result_ref": f"eos.voucher_draft:{voucher_id}",
                "voucher_id": voucher_id,
                "committed_at": _wire_time(committed_at),
                "authorization_revision_hash": (evidence.authorization_revision_hash),
                "authorization_checked_at": _wire_time(
                    evidence.authorization_checked_at
                ),
                "attachment_batch_id": command.attachment_batch_id,
                "attachment_manifest_hash": command.attachment_manifest_hash,
                "attachment_ids": [item.attachment_id for item in command.attachments],
            }

        try:
            transaction = self._coordinator.execute(
                EosBusinessOperationRequest(
                    tenant_id=command.tenant_id,
                    business_operation_id=command.business_operation_id,
                    idempotency_key=command.idempotency_key,
                    operation=EOS_CREATE_VOUCHER_OPERATION,
                    payload_hash=command.payload_hash,
                    event_type="VOUCHER_DRAFT_CREATED",
                ),
                mutation,
            )
        except EosBusinessOperationError as exc:
            raise EosVoucherCommandError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        result = transaction.result
        return {
            "schema_version": EOS_CREATE_VOUCHER_RESULT_SCHEMA,
            "tenant_id": transaction.tenant_id,
            "business_operation_id": transaction.business_operation_id,
            "idempotency_key": transaction.idempotency_key,
            "payload_hash": transaction.payload_hash,
            "commit_state": transaction.commit_state,
            "idempotency_disposition": "CREATED" if transaction.created else "REPLAYED",
            "voucher_ref": {"type": "eos.voucher_draft", "id": result["voucher_id"]},
            "business_transaction_ref": {
                "type": "eos.business_operation",
                "id": transaction.business_operation_id,
            },
            "committed_at": result["committed_at"],
            "outbox_event_ref": {
                "type": "eos.outbox_event",
                "id": transaction.event_id,
            },
            "reason_code": None,
            "reconciliation_ref": None,
        }


def parse_create_voucher_draft_command(
    payload: Mapping[str, Any],
) -> ParsedVoucherDraftCommand:
    required = {
        "schema_version",
        "tenant_id",
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "requester_ref",
        "project_ref",
        "voucher_type",
        "transaction_date",
        "currency",
        "description",
        "lines",
        "nsl_approval_request_id",
        "nsl_approval_evidence_ref",
        "trace",
    }
    optional = {
        "business_approval_proof_ref",
        "attachments",
        "attachment_batch_id",
        "attachment_manifest_hash",
    }
    value = _object(payload, "command", required, optional)
    if value["schema_version"] != EOS_CREATE_VOUCHER_SCHEMA:
        raise _invalid("schema_version is not supported")
    lines = _parse_lines(value["lines"])
    attachments = _parse_attachments(value.get("attachments", ()))
    attachment_batch_id, attachment_manifest_hash = _attachment_lineage(
        value.get("attachment_batch_id"),
        value.get("attachment_manifest_hash"),
        required=bool(attachments),
    )
    return ParsedVoucherDraftCommand(
        tenant_id=_scoped_id("tenant_id", value["tenant_id"]),
        business_operation_id=_uuid(
            "business_operation_id", value["business_operation_id"]
        ),
        idempotency_key=_text("idempotency_key", value["idempotency_key"], 256),
        payload_hash=_hash_ref(value["payload_hash"]),
        requester_ref=_entity_ref("requester_ref", value["requester_ref"]),
        project_ref=_entity_ref(
            "project_ref", value["project_ref"], expected_type="eos.project"
        ),
        voucher_type=_pattern("voucher_type", value["voucher_type"], _CODE),
        transaction_date=_date(value["transaction_date"]),
        currency=_pattern("currency", value["currency"], _CURRENCY),
        description=_text("description", value["description"], 2000),
        lines=lines,
        nsl_approval_request_id=_scoped_id(
            "nsl_approval_request_id", value["nsl_approval_request_id"]
        ),
        nsl_approval_evidence_ref=_scoped_id(
            "nsl_approval_evidence_ref", value["nsl_approval_evidence_ref"]
        ),
        business_approval_proof_ref=(
            _scoped_id(
                "business_approval_proof_ref",
                value["business_approval_proof_ref"],
            )
            if value.get("business_approval_proof_ref") is not None
            else None
        ),
        attachment_batch_id=attachment_batch_id,
        attachment_manifest_hash=attachment_manifest_hash,
        attachments=attachments,
        trace=_trace(value["trace"]),
    )


def voucher_payload_hash(payload: Mapping[str, Any]) -> str:
    return nsl_write_payload_hash_ref(
        parse_create_voucher_draft_command(payload).business_payload()
    )


def _attachment_lineage(
    batch_id: object,
    manifest_hash: object,
    *,
    required: bool,
) -> tuple[str | None, str | None]:
    if batch_id is None and manifest_hash is None and not required:
        return None, None
    if batch_id is None or manifest_hash is None:
        raise _invalid(
            "attachments require attachment_batch_id and attachment_manifest_hash"
        )
    return _uuid("attachment_batch_id", batch_id), _hash_ref(manifest_hash)


def _parse_lines(value: object) -> tuple[VoucherLineInput, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("lines must be an array")
    if not 2 <= len(value) <= 1000:
        raise _invalid("lines must contain 2..1000 items")
    result = []
    for expected_line_no, raw in enumerate(value, start=1):
        line = _object(
            raw,
            "line",
            {
                "line_no",
                "account_ref",
                "signed_amount",
                "economic_category",
                "evidence_refs",
            },
            {"description"},
        )
        if line["line_no"] != expected_line_no:
            raise _invalid("line_no must be contiguous and deterministic")
        amount_text = line["signed_amount"]
        if not isinstance(amount_text, str) or _MONEY.fullmatch(amount_text) is None:
            raise _invalid("signed_amount must be a canonical decimal string")
        amount = Decimal(amount_text)
        account = _entity_ref(
            "account_ref", line["account_ref"], expected_type="eos.account"
        )
        evidence = _id_sequence("evidence_refs", line["evidence_refs"], 20)
        result.append(
            VoucherLineInput(
                account_id=account["id"],
                signed_amount=amount,
                economic_category=_pattern(
                    "economic_category", line["economic_category"], _CODE
                ),
                description=(
                    _text("line.description", line["description"], 1000)
                    if line.get("description") is not None
                    else None
                ),
                evidence_refs=evidence,
            )
        )
    return tuple(result)


def _parse_attachments(value: object) -> tuple[VoucherAttachmentInput, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("attachments must be an array")
    if len(value) > 20:
        raise _invalid("attachments must contain at most 20 items")
    result = []
    for raw in value:
        item = _object(
            raw,
            "attachment",
            {
                "attachment_id",
                "object_ref",
                "display_name",
                "media_type",
                "size_bytes",
                "content_sha256",
            },
            {"evidence_ref"},
        )
        result.append(VoucherAttachmentInput(**item))
    return tuple(result)


def _trace(value: object) -> dict[str, str]:
    item = _object(
        value, "trace", {"trace_id", "correlation_id", "causation_id"}, set()
    )
    return {name: _scoped_id(name, item[name]) for name in sorted(item)}


def _object(
    value: object, field: str, required: set[str], optional: set[str]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object")
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise _invalid(f"{field} fields do not match the canonical contract")
    return dict(value)


def _entity_ref(
    field: str, value: object, *, expected_type: str | None = None
) -> dict[str, str]:
    item = _object(value, field, {"type", "id"}, set())
    ref_type = _scoped_id(f"{field}.type", item["type"])
    if expected_type is not None and ref_type != expected_type:
        raise _invalid(f"{field}.type must be {expected_type}")
    return {"type": ref_type, "id": _scoped_id(f"{field}.id", item["id"])}


def _id_sequence(field: str, value: object, maximum: int) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid(f"{field} must be an array")
    if len(value) > maximum:
        raise _invalid(f"{field} exceeds {maximum} items")
    result = tuple(_scoped_id(field, item) for item in value)
    if len(set(result)) != len(result):
        raise _invalid(f"{field} must contain unique values")
    return result


def _scoped_id(field: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise _invalid(f"{field} has an invalid format")
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _text(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
    ):
        raise _invalid(f"{field} must contain 1..{maximum} canonical characters")
    return value


def _pattern(field: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _invalid(f"{field} has an invalid format")
    return value


def _hash_ref(value: object) -> str:
    if not isinstance(value, str) or _HASH_REF.fullmatch(value) is None:
        raise _invalid("payload_hash must be a sha256 hash reference")
    return value


def _date(value: object) -> date:
    if not isinstance(value, str):
        raise _invalid("transaction_date must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid("transaction_date must be an ISO date") from exc


def _aware_time(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EosVoucherCommandError(
            "EOS_VOUCHER_CLOCK_INVALID",
            "Voucher command clock must return a timezone-aware datetime.",
            status_code=500,
        )
    return value.astimezone(UTC)


def _wire_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> EosVoucherCommandError:
    return EosVoucherCommandError(
        "EOS_VOUCHER_COMMAND_INVALID", detail, status_code=422
    )
