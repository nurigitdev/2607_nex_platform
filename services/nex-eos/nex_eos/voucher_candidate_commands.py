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
from .voucher_candidates import (
    EOS_CREATE_VOUCHER_CANDIDATE_OPERATION,
    EosVoucherCandidateError,
    SqlAlchemyEosVoucherCandidateRepository,
    VoucherCandidateInput,
    VoucherCandidateLineInput,
)
from .voucher_commands import EosServiceCaller

EOS_CREATE_VOUCHER_CANDIDATE_SCHEMA = "eos_voucher_candidate_create.v2"
EOS_CREATE_VOUCHER_CANDIDATE_RESULT_SCHEMA = "eos_voucher_candidate_create_result.v2"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_WORK_CODE = re.compile(r"^FL[0-9]{7}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT_REGISTRATION_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_MONEY = re.compile(r"^(?:0|[1-9][0-9]{0,15})\.[0-9]{4}$")


class EosVoucherCandidateCommandError(RuntimeError):
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
class ParsedVoucherCandidateCreateCommand:
    tenant_id: str
    company_id: str
    business_operation_id: str
    idempotency_key: str
    payload_hash: str
    preparer_subject_id: str
    project_id: str
    project_code: str
    document_envelope_id: str
    approved_document_id: str
    document_revision: int
    approved_document_hash: str
    attachment_manifest_hash: str
    source_kind: str
    source_record_ref: str
    business_work_code: str
    transaction_currency: str
    recognition_date: date
    lines: tuple[VoucherCandidateLineInput, ...]
    trace: dict[str, str]

    def business_payload(self) -> dict[str, Any]:
        return {
            "schema_version": EOS_CREATE_VOUCHER_CANDIDATE_SCHEMA,
            "tenant_id": self.tenant_id,
            "company_id": self.company_id,
            "preparer_subject_id": self.preparer_subject_id,
            "project_ref": {
                "type": "eos.project",
                "id": self.project_id,
                "code": self.project_code,
            },
            "business_approval": {
                "envelope_id": self.document_envelope_id,
                "approved_document_id": self.approved_document_id,
                "document_revision": self.document_revision,
                "approved_document_hash": self.approved_document_hash,
                "attachment_manifest_hash": self.attachment_manifest_hash,
            },
            "candidate": {
                "source_kind": self.source_kind,
                "source_record_ref": self.source_record_ref,
                "business_work_code": self.business_work_code,
                "transaction_currency": self.transaction_currency,
                "recognition_date": self.recognition_date.isoformat(),
                "lines": [
                    {
                        "line_no": line_no,
                        "account_ref": {
                            "type": "eos.account",
                            "id": line.account_id,
                        },
                        "debit_original": format(line.debit_original, ".4f"),
                        "credit_original": format(line.credit_original, ".4f"),
                        "source_record_line_ref": line.source_record_line_ref,
                        "description": line.description,
                        "evidence_hash": line.evidence_hash,
                    }
                    for line_no, line in enumerate(self.lines, start=1)
                ],
            },
        }


class EosCreateVoucherCandidateService:
    def __init__(
        self,
        *,
        coordinator: EosBusinessTransactionCoordinator,
        candidates: SqlAlchemyEosVoucherCandidateRepository,
        authorizer: EosVoucherAuthorizationClient,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._candidates = candidates
        self._authorizer = authorizer
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        payload: Mapping[str, Any],
        *,
        caller: EosServiceCaller,
    ) -> dict[str, Any]:
        command = parse_create_voucher_candidate_command(payload)
        computed_hash = voucher_candidate_payload_hash(command)
        if computed_hash != command.payload_hash:
            raise EosVoucherCandidateCommandError(
                "EOS_VOUCHER_CANDIDATE_PAYLOAD_HASH_MISMATCH",
                "Canonical VoucherCandidate payload hash does not match.",
                status_code=422,
            )
        try:
            authorization = self._authorizer.authorize_create(
                EosAuthorizationTarget(
                    tenant_id=command.tenant_id,
                    subject_id=command.preparer_subject_id,
                    service_subject=caller.subject,
                    service_audience=caller.audience,
                    service_scopes=caller.scopes,
                    project_id=command.project_id,
                    project_code=command.project_code,
                    resource_type="voucher_candidate",
                    resource_id=command.business_operation_id,
                    correlation_id=command.trace["correlation_id"],
                )
            )
        except EosAuthorizationError as exc:
            raise EosVoucherCandidateCommandError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise EosBusinessOperationError(
                    "EOS_VOUCHER_CANDIDATE_TRANSACTION_REQUIRED",
                    "VoucherCandidate creation requires a database transaction.",
                    status_code=500,
                )
            candidate_id = _uuid("candidate_id", self._id_factory())
            revision_id = _uuid("revision_id", self._id_factory())
            try:
                committed_at = _aware_time(self._clock())
            except EosVoucherCandidateCommandError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
            try:
                candidate = self._candidates.create_in_session(
                    session,
                    VoucherCandidateInput(
                        tenant_id=command.tenant_id,
                        candidate_id=candidate_id,
                        revision_id=revision_id,
                        company_id=command.company_id,
                        project_id=command.project_id,
                        project_code=command.project_code,
                        document_envelope_id=command.document_envelope_id,
                        approved_document_id=command.approved_document_id,
                        document_revision=command.document_revision,
                        approved_document_hash=command.approved_document_hash,
                        attachment_manifest_hash=command.attachment_manifest_hash,
                        preparer_subject_id=command.preparer_subject_id,
                        source_kind=command.source_kind,
                        source_record_ref=command.source_record_ref,
                        business_work_code=command.business_work_code,
                        transaction_currency=command.transaction_currency,
                        recognition_date=command.recognition_date,
                        lines=command.lines,
                        created_business_operation_id=command.business_operation_id,
                    ),
                )
            except EosVoucherCandidateError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
            return {
                "business_result_ref": f"eos.voucher_candidate:{candidate_id}",
                "candidate_id": candidate_id,
                "revision_id": revision_id,
                "revision_no": 1,
                "candidate_hash": candidate["revision"]["candidate_hash"],
                "project_id": command.project_id,
                "project_code": command.project_code,
                "document_envelope_id": command.document_envelope_id,
                "authorization_revision_hash": (
                    authorization.authorization_revision_hash
                ),
                "authorization_checked_at": _wire_time(
                    authorization.authorization_checked_at
                ),
                "committed_at": _wire_time(committed_at),
            }

        try:
            transaction = self._coordinator.execute(
                EosBusinessOperationRequest(
                    tenant_id=command.tenant_id,
                    business_operation_id=command.business_operation_id,
                    idempotency_key=command.idempotency_key,
                    operation=EOS_CREATE_VOUCHER_CANDIDATE_OPERATION,
                    payload_hash=command.payload_hash,
                    event_type="VOUCHER_CANDIDATE_CREATED",
                ),
                mutation,
            )
        except EosBusinessOperationError as exc:
            raise EosVoucherCandidateCommandError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        result = transaction.result
        return {
            "schema_version": EOS_CREATE_VOUCHER_CANDIDATE_RESULT_SCHEMA,
            "tenant_id": transaction.tenant_id,
            "business_operation_id": transaction.business_operation_id,
            "idempotency_key": transaction.idempotency_key,
            "payload_hash": transaction.payload_hash,
            "commit_state": transaction.commit_state,
            "idempotency_disposition": (
                "CREATED" if transaction.created else "REPLAYED"
            ),
            "candidate_ref": {
                "type": "eos.voucher_candidate",
                "id": result["candidate_id"],
            },
            "revision_ref": {
                "type": "eos.voucher_candidate_revision",
                "id": result["revision_id"],
                "revision_no": result["revision_no"],
                "hash": result["candidate_hash"],
            },
            "project_ref": {
                "type": "eos.project",
                "id": result["project_id"],
                "code": result["project_code"],
            },
            "document_envelope_id": result["document_envelope_id"],
            "committed_at": result["committed_at"],
            "outbox_event_ref": {
                "type": "eos.outbox_event",
                "id": transaction.event_id,
            },
        }


def parse_create_voucher_candidate_command(
    payload: Mapping[str, Any],
) -> ParsedVoucherCandidateCreateCommand:
    value = _object(
        payload,
        "command",
        {
            "schema_version",
            "tenant_id",
            "company_id",
            "business_operation_id",
            "idempotency_key",
            "payload_hash",
            "preparer_subject_id",
            "project_ref",
            "business_approval",
            "candidate",
            "trace",
        },
    )
    if value["schema_version"] != EOS_CREATE_VOUCHER_CANDIDATE_SCHEMA:
        raise _invalid("schema_version is not supported.")
    project = _object(value["project_ref"], "project_ref", {"type", "id", "code"})
    if project["type"] != "eos.project":
        raise _invalid("project_ref.type must be eos.project.")
    project_code = _pattern(
        "project_ref.code", project["code"], _PROJECT_REGISTRATION_CODE
    )
    approval = _object(
        value["business_approval"],
        "business_approval",
        {
            "envelope_id",
            "approved_document_id",
            "document_revision",
            "approved_document_hash",
            "attachment_manifest_hash",
        },
    )
    candidate = _object(
        value["candidate"],
        "candidate",
        {
            "source_kind",
            "source_record_ref",
            "business_work_code",
            "transaction_currency",
            "recognition_date",
            "lines",
        },
    )
    return ParsedVoucherCandidateCreateCommand(
        tenant_id=_scoped_id("tenant_id", value["tenant_id"], 128),
        company_id=_uuid("company_id", value["company_id"]),
        business_operation_id=_uuid(
            "business_operation_id", value["business_operation_id"]
        ),
        idempotency_key=_text("idempotency_key", value["idempotency_key"], 256),
        payload_hash=_hash_ref("payload_hash", value["payload_hash"]),
        preparer_subject_id=_scoped_id(
            "preparer_subject_id", value["preparer_subject_id"], 128
        ),
        project_id=_uuid("project_ref.id", project["id"]),
        project_code=project_code,
        document_envelope_id=_uuid(
            "business_approval.envelope_id", approval["envelope_id"]
        ),
        approved_document_id=_scoped_id(
            "business_approval.approved_document_id",
            approval["approved_document_id"],
            128,
        ),
        document_revision=_positive_int(
            "business_approval.document_revision", approval["document_revision"]
        ),
        approved_document_hash=_hash_ref(
            "business_approval.approved_document_hash",
            approval["approved_document_hash"],
        ),
        attachment_manifest_hash=_hash_ref(
            "business_approval.attachment_manifest_hash",
            approval["attachment_manifest_hash"],
        ),
        source_kind=_pattern("candidate.source_kind", candidate["source_kind"], _CODE),
        source_record_ref=_scoped_id(
            "candidate.source_record_ref", candidate["source_record_ref"], 256
        ),
        business_work_code=_pattern(
            "candidate.business_work_code",
            candidate["business_work_code"],
            _WORK_CODE,
        ),
        transaction_currency=_pattern(
            "candidate.transaction_currency",
            candidate["transaction_currency"],
            _CURRENCY,
        ),
        recognition_date=_date(
            "candidate.recognition_date", candidate["recognition_date"]
        ),
        lines=_parse_lines(candidate["lines"]),
        trace=_trace(value["trace"]),
    )


def voucher_candidate_payload_hash(
    value: ParsedVoucherCandidateCreateCommand | Mapping[str, Any],
) -> str:
    command = (
        value
        if isinstance(value, ParsedVoucherCandidateCreateCommand)
        else parse_create_voucher_candidate_command(value)
    )
    return nsl_write_payload_hash_ref(command.business_payload())


def _parse_lines(value: object) -> tuple[VoucherCandidateLineInput, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("candidate.lines must be an array.")
    if not 2 <= len(value) <= 1000:
        raise _invalid("candidate.lines must contain 2..1000 items.")
    result = []
    for expected_line_no, raw in enumerate(value, start=1):
        line = _object(
            raw,
            "candidate.line",
            {
                "line_no",
                "account_ref",
                "debit_original",
                "credit_original",
                "source_record_line_ref",
                "description",
                "evidence_hash",
            },
        )
        if line["line_no"] != expected_line_no:
            raise _invalid("candidate line_no must be contiguous.")
        account = _object(line["account_ref"], "account_ref", {"type", "id"})
        if account["type"] != "eos.account":
            raise _invalid("account_ref.type must be eos.account.")
        debit = _money("debit_original", line["debit_original"])
        credit = _money("credit_original", line["credit_original"])
        if (debit > 0) == (credit > 0):
            raise _invalid("Each Candidate line must contain one debit or credit.")
        result.append(
            VoucherCandidateLineInput(
                account_id=_uuid("account_ref.id", account["id"]),
                debit_original=debit,
                credit_original=credit,
                source_record_line_ref=_scoped_id(
                    "source_record_line_ref", line["source_record_line_ref"], 256
                ),
                description=(
                    _text("description", line["description"], 1000)
                    if line["description"] is not None
                    else None
                ),
                evidence_hash=_hash_ref("evidence_hash", line["evidence_hash"]),
            )
        )
    return tuple(result)


def _trace(value: object) -> dict[str, str]:
    raw = _object(value, "trace", {"trace_id", "correlation_id", "causation_id"})
    return {
        name: _scoped_id(f"trace.{name}", raw[name], 128)
        for name in ("trace_id", "correlation_id", "causation_id")
    }


def _object(
    value: object,
    field_name: str,
    required: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != required:
        raise _invalid(f"{field_name} must contain exactly {sorted(required)}.")
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID.") from exc


def _scoped_id(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if len(normalized) > maximum or _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} has invalid stable-reference syntax.")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(f"{field_name} must contain 1..{maximum} characters.")
    return normalized


def _pattern(field_name: str, value: object, pattern: re.Pattern[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if pattern.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} has invalid syntax.")
    return normalized


def _hash_ref(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _HASH_REF.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} must be a SHA-256 hash reference.")
    return normalized


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field_name} must be a positive integer.")
    return value


def _date(field_name: str, value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise _invalid(f"{field_name} must be an ISO date.") from exc


def _money(field_name: str, value: object) -> Decimal:
    if not isinstance(value, str) or _MONEY.fullmatch(value) is None:
        raise _invalid(f"{field_name} must be a canonical non-negative decimal.")
    return Decimal(value)


def _aware_time(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EosVoucherCandidateCommandError(
            "EOS_VOUCHER_CANDIDATE_CLOCK_INVALID",
            "VoucherCandidate clock must be timezone-aware.",
            status_code=500,
        )
    return value.astimezone(UTC)


def _wire_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> EosVoucherCandidateCommandError:
    return EosVoucherCandidateCommandError(
        "EOS_VOUCHER_CANDIDATE_COMMAND_INVALID",
        detail,
        status_code=422,
    )
