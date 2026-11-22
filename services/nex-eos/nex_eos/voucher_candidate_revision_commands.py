from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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
from .candidate_review import (
    EosCandidateReviewError,
    SqlAlchemyEosCandidateReviewRepository,
)
from .voucher_candidate_commands import EosVoucherCandidateCommandError
from .voucher_candidates import (
    EosVoucherCandidateError,
    SqlAlchemyEosVoucherCandidateRepository,
    VoucherCandidateLineInput,
    VoucherCandidateRevisionInput,
)
from .voucher_commands import EosServiceCaller

EOS_REVISE_VOUCHER_CANDIDATE_OPERATION = "FINANCE.VOUCHER_CANDIDATE.REVISE"
EOS_REVISE_VOUCHER_CANDIDATE_SCHEMA = "eos_voucher_candidate_revise.v1"
EOS_REVISE_VOUCHER_CANDIDATE_RESULT_SCHEMA = "eos_voucher_candidate_revise_result.v1"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_MONEY = re.compile(r"^(?:0|[1-9][0-9]{0,15})\.[0-9]{4}$")


@dataclass(frozen=True)
class ParsedVoucherCandidateRevisionCommand:
    tenant_id: str
    business_operation_id: str
    idempotency_key: str
    payload_hash: str
    actor_subject_id: str
    candidate_id: str
    expected_candidate_version: int
    expected_revision_no: int
    expected_candidate_hash: str
    return_event_id: str
    lines: tuple[VoucherCandidateLineInput, ...]
    trace: dict[str, str]

    def business_payload(self) -> dict[str, Any]:
        return {
            "schema_version": EOS_REVISE_VOUCHER_CANDIDATE_SCHEMA,
            "tenant_id": self.tenant_id,
            "actor_subject_id": self.actor_subject_id,
            "candidate_ref": {
                "type": "eos.voucher_candidate",
                "id": self.candidate_id,
                "expected_version": self.expected_candidate_version,
                "expected_revision_no": self.expected_revision_no,
                "expected_hash": self.expected_candidate_hash,
            },
            "return_event_ref": {
                "type": "eos.candidate_review_event",
                "id": self.return_event_id,
            },
            "replacement": {
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
                ]
            },
        }


class EosReviseVoucherCandidateService:
    def __init__(
        self,
        *,
        coordinator: EosBusinessTransactionCoordinator,
        candidates: SqlAlchemyEosVoucherCandidateRepository,
        reviews: SqlAlchemyEosCandidateReviewRepository,
        authorizer: EosVoucherAuthorizationClient,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._candidates = candidates
        self._reviews = reviews
        self._authorizer = authorizer
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        candidate_id: str,
        payload: Mapping[str, Any],
        *,
        caller: EosServiceCaller,
    ) -> dict[str, Any]:
        path_candidate_id = _uuid("candidate_id", candidate_id)
        command = parse_revise_voucher_candidate_command(payload)
        if command.candidate_id != path_candidate_id:
            raise _invalid("Path candidate_id differs from candidate_ref.id.")
        computed_hash = voucher_candidate_revision_payload_hash(command)
        if computed_hash != command.payload_hash:
            raise EosVoucherCandidateCommandError(
                "EOS_VOUCHER_CANDIDATE_PAYLOAD_HASH_MISMATCH",
                "Canonical VoucherCandidate revision payload hash does not match.",
                status_code=422,
            )
        current = self._load_current(command)
        try:
            authorization = self._authorizer.authorize_create(
                EosAuthorizationTarget(
                    tenant_id=command.tenant_id,
                    subject_id=command.actor_subject_id,
                    service_subject=caller.subject,
                    service_audience=caller.audience,
                    service_scopes=caller.scopes,
                    project_id=str(current["project_id"]),
                    project_code=str(current["project_code"]),
                    resource_type="voucher_candidate",
                    resource_id=command.candidate_id,
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
                    "VoucherCandidate revision requires a database transaction.",
                    status_code=500,
                )
            try:
                self._reviews.require_return_event_in_session(
                    session,
                    tenant_id=command.tenant_id,
                    candidate_id=command.candidate_id,
                    candidate_revision=command.expected_revision_no,
                    event_id=command.return_event_id,
                )
                revised = self._candidates.append_revision_in_session(
                    session,
                    VoucherCandidateRevisionInput(
                        tenant_id=command.tenant_id,
                        candidate_id=command.candidate_id,
                        revision_id=_uuid("revision_id", self._id_factory()),
                        expected_candidate_version=(command.expected_candidate_version),
                        expected_revision_no=command.expected_revision_no,
                        expected_candidate_hash=command.expected_candidate_hash,
                        actor_subject_id=command.actor_subject_id,
                        lines=command.lines,
                    ),
                )
            except (EosCandidateReviewError, EosVoucherCandidateError) as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
            try:
                committed_at = _aware_time(self._clock())
            except EosVoucherCandidateCommandError as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                ) from exc
            revision = revised["revision"]
            return {
                "business_result_ref": (
                    f"eos.voucher_candidate:{command.candidate_id}"
                ),
                "candidate_id": command.candidate_id,
                "revision_id": str(revision["revision_id"]),
                "revision_no": int(revision["revision_no"]),
                "candidate_hash": str(revision["candidate_hash"]),
                "previous_revision_no": command.expected_revision_no,
                "project_id": str(revised["project_id"]),
                "project_code": str(revised["project_code"]),
                "return_event_id": command.return_event_id,
                "candidate_state": str(revised["state"]),
                "candidate_version": int(revised["version"]),
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
                    operation=EOS_REVISE_VOUCHER_CANDIDATE_OPERATION,
                    payload_hash=command.payload_hash,
                    event_type="VOUCHER_CANDIDATE_REVISED",
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
            "schema_version": EOS_REVISE_VOUCHER_CANDIDATE_RESULT_SCHEMA,
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
                "state": result["candidate_state"],
                "version": result["candidate_version"],
            },
            "previous_revision_no": result["previous_revision_no"],
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
            "return_event_ref": {
                "type": "eos.candidate_review_event",
                "id": result["return_event_id"],
            },
            "committed_at": result["committed_at"],
            "outbox_event_ref": {
                "type": "eos.outbox_event",
                "id": transaction.event_id,
            },
        }

    def _load_current(
        self, command: ParsedVoucherCandidateRevisionCommand
    ) -> Mapping[str, Any]:
        try:
            current = self._candidates.get(
                tenant_id=command.tenant_id,
                candidate_id=command.candidate_id,
            )
        except EosVoucherCandidateError as exc:
            raise EosVoucherCandidateCommandError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        if current is None:
            raise EosVoucherCandidateCommandError(
                "EOS_VOUCHER_CANDIDATE_NOT_FOUND",
                "VoucherCandidate was not found in tenant scope.",
                status_code=404,
            )
        return current


def parse_revise_voucher_candidate_command(
    payload: Mapping[str, Any],
) -> ParsedVoucherCandidateRevisionCommand:
    value = _object(
        payload,
        "command",
        {
            "schema_version",
            "tenant_id",
            "business_operation_id",
            "idempotency_key",
            "payload_hash",
            "actor_subject_id",
            "candidate_ref",
            "return_event_ref",
            "replacement",
            "trace",
        },
    )
    if value["schema_version"] != EOS_REVISE_VOUCHER_CANDIDATE_SCHEMA:
        raise _invalid("schema_version is not supported.")
    candidate = _object(
        value["candidate_ref"],
        "candidate_ref",
        {
            "type",
            "id",
            "expected_version",
            "expected_revision_no",
            "expected_hash",
        },
    )
    if candidate["type"] != "eos.voucher_candidate":
        raise _invalid("candidate_ref.type must be eos.voucher_candidate.")
    return_event = _object(
        value["return_event_ref"],
        "return_event_ref",
        {"type", "id"},
    )
    if return_event["type"] != "eos.candidate_review_event":
        raise _invalid("return_event_ref.type must be eos.candidate_review_event.")
    replacement = _object(
        value["replacement"],
        "replacement",
        {"lines"},
    )
    return ParsedVoucherCandidateRevisionCommand(
        tenant_id=_scoped_id("tenant_id", value["tenant_id"], 128),
        business_operation_id=_uuid(
            "business_operation_id", value["business_operation_id"]
        ),
        idempotency_key=_text("idempotency_key", value["idempotency_key"], 256),
        payload_hash=_hash_ref("payload_hash", value["payload_hash"]),
        actor_subject_id=_scoped_id("actor_subject_id", value["actor_subject_id"], 128),
        candidate_id=_uuid("candidate_ref.id", candidate["id"]),
        expected_candidate_version=_positive_int(
            "candidate_ref.expected_version", candidate["expected_version"]
        ),
        expected_revision_no=_positive_int(
            "candidate_ref.expected_revision_no",
            candidate["expected_revision_no"],
        ),
        expected_candidate_hash=_hash_ref(
            "candidate_ref.expected_hash", candidate["expected_hash"]
        ),
        return_event_id=_uuid("return_event_ref.id", return_event["id"]),
        lines=_parse_lines(replacement["lines"]),
        trace=_trace(value["trace"]),
    )


def voucher_candidate_revision_payload_hash(
    value: ParsedVoucherCandidateRevisionCommand | Mapping[str, Any],
) -> str:
    command = (
        value
        if isinstance(value, ParsedVoucherCandidateRevisionCommand)
        else parse_revise_voucher_candidate_command(value)
    )
    return nsl_write_payload_hash_ref(command.business_payload())


def _parse_lines(value: object) -> tuple[VoucherCandidateLineInput, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("replacement.lines must be an array.")
    if not 2 <= len(value) <= 1000:
        raise _invalid("replacement.lines must contain 2..1000 items.")
    result = []
    for expected_line_no, raw in enumerate(value, start=1):
        line = _object(
            raw,
            "replacement.line",
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
            raise _invalid("replacement line_no must be contiguous.")
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


def _hash_ref(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _HASH_REF.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} must be a SHA-256 hash reference.")
    return normalized


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field_name} must be a positive integer.")
    return value


def _money(field_name: str, value: object) -> Decimal:
    normalized = str(value).strip() if value is not None else ""
    if _MONEY.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} must use canonical four-decimal money.")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise _invalid(f"{field_name} is not valid decimal money.") from exc


def _aware_time(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EosVoucherCandidateCommandError(
            "EOS_VOUCHER_CANDIDATE_CLOCK_INVALID",
            "VoucherCandidate command clock must be timezone-aware.",
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
