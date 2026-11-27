from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy.orm import Session

from .accounts import SqlAlchemyEosAccountRepository
from .approval_policies import (
    ApprovalPolicySelection,
    SqlAlchemyEosApprovalPolicyRepository,
)
from .approved_documents import SqlAlchemyEosApprovedDocumentRepository
from .business_journeys import project_voucher_journey
from .business_transactions import (
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .candidate_review import (
    EosCandidateReviewError,
    SqlAlchemyEosCandidateReviewRepository,
)
from .candidate_validation import EosCandidateValidationService
from .projects import SqlAlchemyEosProjectRepository
from .scoped_approvals import EosScopedApprovalService, scoped_approval_payload_hash
from .voucher_candidate_commands import (
    EosCreateVoucherCandidateService,
    ParsedVoucherCandidateCreateCommand,
    voucher_candidate_payload_hash,
)
from .voucher_candidates import (
    EosVoucherCandidateError,
    SqlAlchemyEosVoucherCandidateRepository,
    VoucherCandidateLineInput,
    VoucherCandidateRevisionInput,
)
from .voucher_commands import EosServiceCaller

CREATE_DRAFT_OPERATION = "FINANCE.VOUCHER_PRE_SUBMISSION.CREATE"
REVISE_DRAFT_OPERATION = "FINANCE.VOUCHER_PRE_SUBMISSION.REVISE"
SUBMIT_DRAFT_OPERATION = "FINANCE.VOUCHER_PRE_SUBMISSION.SUBMIT_FOR_ACCOUNTING"
_REVISION_EVENT = "VOUCHER_CANDIDATE_REVISED"


class EosBusinessVoucherDraftError(RuntimeError):
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
class DraftLineInput:
    account_code: str
    debit_original: Decimal
    credit_original: Decimal
    source_record_line_ref: str
    evidence_hash: str
    description: str | None = None


class EosBusinessVoucherDraftService:
    def __init__(
        self,
        *,
        coordinator: EosBusinessTransactionCoordinator,
        candidates: SqlAlchemyEosVoucherCandidateRepository,
        candidate_reviews: SqlAlchemyEosCandidateReviewRepository,
        create_service: EosCreateVoucherCandidateService,
        validation_service: EosCandidateValidationService,
        scoped_approvals: EosScopedApprovalService,
        approval_policies: SqlAlchemyEosApprovalPolicyRepository,
        approved_documents: SqlAlchemyEosApprovedDocumentRepository,
        projects: SqlAlchemyEosProjectRepository,
        accounts: SqlAlchemyEosAccountRepository,
        clock=None,
    ) -> None:
        self._coordinator = coordinator
        self._candidates = candidates
        self._candidate_reviews = candidate_reviews
        self._create_service = create_service
        self._validation_service = validation_service
        self._scoped_approvals = scoped_approvals
        self._approval_policies = approval_policies
        self._approved_documents = approved_documents
        self._projects = projects
        self._accounts = accounts
        self._clock = clock or (lambda: datetime.now(UTC))

    def list_owner(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        states: Sequence[str] = (),
    ) -> dict[str, Any]:
        return {
            "schema_version": "eos_business_voucher_draft_list.v1",
            "items": [
                self._project(candidate)
                for candidate in self._candidates.list_preparer(
                    tenant_id=tenant_id,
                    preparer_subject_id=subject_id,
                    states=states,
                )
            ],
        }

    def get_owner(
        self, *, tenant_id: str, subject_id: str, candidate_id: str
    ) -> dict[str, Any]:
        candidate = self._require_owner(tenant_id, subject_id, candidate_id)
        projection = self._project(candidate)
        projection["revisions"] = [
            self._project_revision(tenant_id, item)
            for item in self._candidates.list_revisions(
                tenant_id=tenant_id,
                candidate_id=candidate_id,
            )
        ]
        return projection

    def create(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        payload: Mapping[str, Any],
        caller: EosServiceCaller,
    ) -> dict[str, Any]:
        command_id = _uuid("client_command_id", payload.get("client_command_id"))
        envelope = self._require_envelope(
            tenant_id, _uuid("envelope_id", payload.get("envelope_id"))
        )
        recognition_date = _date("recognition_date", payload.get("recognition_date"))
        project = self._require_project(
            tenant_id,
            _project_code(payload.get("project_code")),
            envelope=envelope,
        )
        lines = self._resolve_lines(
            tenant_id,
            recognition_date,
            _draft_lines(payload.get("lines")),
        )
        _require_amount_within_envelope(lines, envelope)
        parsed = ParsedVoucherCandidateCreateCommand(
            tenant_id=tenant_id,
            company_id=str(envelope["company_id"]),
            business_operation_id=command_id,
            idempotency_key=f"business-voucher-draft:create:{command_id}",
            payload_hash="sha256:" + "0" * 64,
            preparer_subject_id=subject_id,
            project_id=str(project["project_id"]),
            project_code=str(project["project_code"]),
            document_envelope_id=str(envelope["envelope_id"]),
            approved_document_id=str(envelope["approved_document_id"]),
            document_revision=int(envelope["document_revision"]),
            approved_document_hash=str(envelope["document_content_hash"]),
            attachment_manifest_hash=str(envelope["attachment_manifest_hash"]),
            source_kind=_code("source_kind", payload.get("source_kind")),
            source_record_ref=_text(
                "source_record_ref", payload.get("source_record_ref"), 256
            ),
            business_work_code=str(envelope["work_code"]),
            transaction_currency=str(envelope["approved_currency"]),
            recognition_date=recognition_date,
            lines=tuple(lines),
            trace=_trace(payload.get("trace"), fallback=command_id),
        )
        command = {
            **parsed.business_payload(),
            "business_operation_id": command_id,
            "idempotency_key": parsed.idempotency_key,
            "payload_hash": voucher_candidate_payload_hash(parsed),
            "trace": parsed.trace,
        }
        result = self._create_service.execute(command, caller=caller)
        return self.get_owner(
            tenant_id=tenant_id,
            subject_id=subject_id,
            candidate_id=str(result["candidate_ref"]["id"]),
        )

    def revise(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        candidate_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        candidate = self._require_owner(tenant_id, subject_id, candidate_id)
        if candidate["state"] not in {"DRAFT", "RETURNED_FOR_CORRECTION"}:
            raise _conflict(
                "Only a DRAFT or returned VoucherCandidate may be revised."
            )
        correction_reentry = candidate["state"] == "RETURNED_FOR_CORRECTION"
        command_id = _uuid("client_command_id", payload.get("client_command_id"))
        expected_version = _positive_int("expected_version", payload.get("expected_version"))
        expected_revision = _positive_int(
            "expected_revision", payload.get("expected_revision")
        )
        expected_hash = _hash_ref("expected_candidate_hash", payload.get("expected_candidate_hash"))
        recognition_date = _date("recognition_date", payload.get("recognition_date"))
        lines = self._resolve_lines(
            tenant_id,
            recognition_date,
            _draft_lines(payload.get("lines")),
        )
        envelope = self._require_envelope(tenant_id, str(candidate["document_envelope_id"]))
        _require_amount_within_envelope(lines, envelope)
        semantics = {
            "candidate_id": candidate_id,
            "expected_version": expected_version,
            "expected_revision": expected_revision,
            "expected_candidate_hash": expected_hash,
            "recognition_date": recognition_date.isoformat(),
            "lines": [_line_semantics(line) for line in lines],
        }
        payload_hash = semantic_sha256_hash_ref(
            {"domain": "EOS-BUSINESS-VOUCHER-DRAFT-REVISION-V1", **semantics}
        )

        def mutation(session: Session | None) -> Mapping[str, Any]:
            if session is None:
                raise EosBusinessOperationError(
                    "EOS_BUSINESS_VOUCHER_TRANSACTION_REQUIRED",
                    "Voucher draft revision requires a database transaction.",
                    status_code=500,
                )
            revision_input = VoucherCandidateRevisionInput(
                tenant_id=tenant_id,
                candidate_id=candidate_id,
                revision_id=str(
                    uuid5(NAMESPACE_URL, f"{tenant_id}:{command_id}:revision")
                ),
                expected_candidate_version=expected_version,
                expected_revision_no=expected_revision,
                expected_candidate_hash=expected_hash,
                actor_subject_id=subject_id,
                recognition_date=recognition_date,
                lines=lines,
            )
            try:
                if correction_reentry:
                    self._candidate_reviews.require_latest_return_event_in_session(
                        session,
                        tenant_id=tenant_id,
                        candidate_id=candidate_id,
                        candidate_revision=expected_revision,
                    )
                    revised = self._candidates.append_revision_in_session(
                        session, revision_input
                    )
                else:
                    revised = self._candidates.append_draft_revision_in_session(
                        session, revision_input
                    )
            except (EosCandidateReviewError, EosVoucherCandidateError) as exc:
                raise EosBusinessOperationError(
                    exc.error_code,
                    exc.detail,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc
            return {
                "business_result_ref": f"eos.voucher_candidate:{candidate_id}",
                "candidate_id": candidate_id,
                "revision_no": revised["revision"]["revision_no"],
                "candidate_hash": revised["revision"]["candidate_hash"],
            }

        try:
            self._coordinator.execute(
                EosBusinessOperationRequest(
                    tenant_id=tenant_id,
                    business_operation_id=command_id,
                    idempotency_key=f"business-voucher-draft:revise:{command_id}",
                    operation=REVISE_DRAFT_OPERATION,
                    payload_hash=payload_hash,
                    event_type=_REVISION_EVENT,
                ),
                mutation,
            )
        except EosBusinessOperationError as exc:
            raise EosBusinessVoucherDraftError(
                exc.error_code,
                exc.detail,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        return self.get_owner(
            tenant_id=tenant_id,
            subject_id=subject_id,
            candidate_id=candidate_id,
        )

    def validate(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        candidate_id: str,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        candidate = self._require_owner(tenant_id, subject_id, candidate_id)
        observed_at = _aware(as_of or self._clock())
        return self._validation_service.validate(
            candidate_id,
            {
                "schema_version": "eos_voucher_candidate_validate.v1",
                "tenant_id": tenant_id,
                "expected_revision_no": int(candidate["current_revision_no"]),
                "expected_candidate_hash": str(candidate["revision"]["candidate_hash"]),
                "as_of": _timestamp(observed_at),
            },
        )

    def submit(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        candidate_id: str,
        payload: Mapping[str, Any],
        caller: EosServiceCaller,
    ) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise _invalid("confirmed must be true for accounting submission.")
        candidate = self._require_owner(tenant_id, subject_id, candidate_id)
        expected_version = _positive_int("expected_version", payload.get("expected_version"))
        expected_revision = _positive_int(
            "expected_revision", payload.get("expected_revision")
        )
        expected_hash = _hash_ref("expected_candidate_hash", payload.get("expected_candidate_hash"))
        command_id = _uuid("client_command_id", payload.get("client_command_id"))
        case_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{tenant_id}:{candidate_id}:{expected_revision}:accounting-case",
            )
        )
        replay = self._scoped_approvals.replay_accounting_case(
            tenant_id=tenant_id,
            case_id=case_id,
            business_operation_id=command_id,
            requester_subject_id=subject_id,
            subject_ref=f"eos.voucher-candidate:{candidate_id}",
            subject_revision=expected_revision,
            subject_hash=expected_hash,
            caller=caller,
        )
        if replay is not None:
            return replay
        if (
            int(candidate["version"]) != expected_version
            or int(candidate["current_revision_no"]) != expected_revision
            or str(candidate["revision"]["candidate_hash"]) != expected_hash
        ):
            raise _conflict("Voucher draft changed before accounting submission.")
        now = _aware(self._clock())
        validation = self.validate(
            tenant_id=tenant_id,
            subject_id=subject_id,
            candidate_id=candidate_id,
            as_of=now,
        )
        account_ids = [str(line["account_id"]) for line in candidate["lines"]]
        policy = self._approval_policies.resolve_policy(
            ApprovalPolicySelection(
                tenant_id=tenant_id,
                approval_domain="BUSINESS_FORMAL",
                risk_level=None,
                amount=Decimal(str(validation["totals"]["debit_original"])),
                transaction_type="ACCOUNTING_POSTING",
                effective_at=now,
                project_id=str(candidate["project_id"]),
                account_ids=account_ids,
            )
        )
        if policy is None:
            raise EosBusinessVoucherDraftError(
                "EOS_ACCOUNTING_APPROVAL_POLICY_NOT_FOUND",
                "No fresh accounting approval policy matches the VoucherCandidate.",
                status_code=409,
            )
        envelope = self._require_envelope(tenant_id, str(candidate["document_envelope_id"]))
        fx = validation["fx_evidence"]
        review = {
            "schema_version": "eos_accounting_review_context.v3",
            "candidate_id": candidate_id,
            "candidate_revision": expected_revision,
            "candidate_hash": expected_hash,
            "candidate_version": expected_version,
            "validation_hash": validation["validation_hash"],
            "validation_observed_at": validation["observed_at"],
            "document_envelope_hash": validation["document_ref"]["hash"],
            "fx_rate_set_hash": validation["fx_rate_set_hash"],
            "rule_release_hash": validation["posting_rule_release_hash"],
            "accounting_period_id": validation["accounting_period_id"],
            "candidate_preparer_subject_id": subject_id,
            "business_approver_subject_ids": [
                str(envelope["approved_by_principal_ref"]["id"])
            ],
            "original_currency": validation["transaction_currency"],
            "original_amount": validation["totals"]["debit_original"],
            "market_base_rate": fx["normalized_rate"],
            "rate_reference_date": fx["selected_rate_date"],
            "rate_publication": _rate_publication(fx),
            "functional_currency": validation["functional_currency"],
            "functional_amount": validation["totals"]["debit_functional"],
            "fx_exception": None,
        }
        case = {
            "tenant_id": tenant_id,
            "case_id": case_id,
            "company_id": str(candidate["company_id"]),
            "purpose": "ACCOUNTING_POSTING",
            "scope_type": "PROJECT",
            "project_ids": [str(candidate["project_id"])],
            "subject_ref": f"eos.voucher-candidate:{candidate_id}",
            "subject_revision": expected_revision,
            "subject_hash": expected_hash,
            "requester_subject_id": subject_id,
            "approval_policy_id": str(policy["approval_policy_id"]),
            "correlation_id": _text(
                "correlation_id", payload.get("correlation_id") or command_id, 128
            ),
            "causation_id": _text(
                "causation_id", payload.get("causation_id") or candidate_id, 128
            ),
            "expires_at": _timestamp(now + timedelta(days=7)),
            "accounting_review": review,
        }
        request = {
            "tenant_id": tenant_id,
            "business_operation_id": command_id,
            "idempotency_key": f"business-voucher-draft:submit:{command_id}",
            "requested_operation": "FINANCE.ACCOUNTING_APPROVAL.REQUEST",
            "case": case,
        }
        request["payload_hash"] = scoped_approval_payload_hash(request)
        return self._scoped_approvals.request_case(request, caller=caller)

    def _require_owner(
        self, tenant_id: str, subject_id: str, candidate_id: str
    ) -> Mapping[str, Any]:
        candidate = self._candidates.get(
            tenant_id=tenant_id,
            candidate_id=_uuid("candidate_id", candidate_id),
        )
        if candidate is None or candidate["preparer_subject_id"] != subject_id:
            raise EosBusinessVoucherDraftError(
                "EOS_BUSINESS_VOUCHER_DRAFT_NOT_FOUND",
                "Voucher draft was not found in the requester scope.",
                status_code=404,
            )
        return candidate

    def _require_envelope(self, tenant_id: str, envelope_id: str) -> Mapping[str, Any]:
        envelope = self._approved_documents.get(
            tenant_id=tenant_id,
            envelope_id=envelope_id,
        )
        if envelope is None or not envelope["usable"]:
            raise _conflict("ApprovedDocumentEnvelope is not currently usable.")
        return envelope

    def _require_project(
        self,
        tenant_id: str,
        project_code: str,
        *,
        envelope: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        project = self._projects.get_project_by_code(
            tenant_id=tenant_id,
            project_code=project_code,
            active_only=True,
        )
        allowed_codes = tuple(str(item) for item in envelope.get("allowed_project_codes", ()))
        allowed_ids = tuple(str(item) for item in envelope["allowed_project_ids"])
        if (
            project is None
            or str(project["project_id"]) not in allowed_ids
            or (allowed_codes and str(project["project_code"]) not in allowed_codes)
        ):
            raise _conflict("Project is not active or is outside the approved envelope.")
        return project

    def _resolve_lines(
        self,
        tenant_id: str,
        effective_at: date,
        values: Sequence[DraftLineInput],
    ) -> list[VoucherCandidateLineInput]:
        result = []
        for value in values:
            account = self._accounts.get_effective_account_by_code(
                tenant_id=tenant_id,
                account_code=value.account_code,
                effective_at=effective_at,
            )
            if account is None:
                raise _conflict(f"Account {value.account_code} is not effective.")
            result.append(
                VoucherCandidateLineInput(
                    account_id=str(account["account_id"]),
                    debit_original=value.debit_original,
                    credit_original=value.credit_original,
                    source_record_line_ref=value.source_record_line_ref,
                    evidence_hash=value.evidence_hash,
                    description=value.description,
                )
            )
        return result

    def _project(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        lines = [self._project_line(str(candidate["tenant_id"]), line) for line in candidate["lines"]]
        debit = sum((Decimal(str(line["debit_original"])) for line in lines), Decimal(0))
        credit = sum((Decimal(str(line["credit_original"])) for line in lines), Decimal(0))
        envelope = self._approved_documents.get(
            tenant_id=str(candidate["tenant_id"]),
            envelope_id=str(candidate["document_envelope_id"]),
        )
        projection = {
            "schema_version": "eos_business_voucher_draft.v1",
            "candidate_id": str(candidate["candidate_id"]),
            "state": str(candidate["state"]),
            "version": int(candidate["version"]),
            "current_revision_no": int(candidate["current_revision_no"]),
            "candidate_hash": str(candidate["revision"]["candidate_hash"]),
            "company_id": str(candidate["company_id"]),
            "project_code": str(candidate["project_code"]),
            "recognition_date": candidate["recognition_date"].isoformat(),
            "transaction_currency": str(candidate["transaction_currency"]),
            "source_kind": str(candidate["source_kind"]),
            "source_record_ref": str(candidate["source_record_ref"]),
            "business_work_code": str(candidate["business_work_code"]),
            "document_envelope_id": str(candidate["document_envelope_id"]),
            "approved_document": (
                {
                    "approved_document_id": envelope["approved_document_id"],
                    "approved_amount": envelope["approved_amount"],
                    "remaining_amount": envelope["remaining_amount"],
                    "attachment_manifest_hash": envelope["attachment_manifest_hash"],
                }
                if envelope is not None
                else None
            ),
            "lines": lines,
            "balance": {
                "debit": format(debit, ".4f"),
                "credit": format(credit, ".4f"),
                "balanced": debit == credit and debit > 0,
            },
            "created_at": _timestamp(candidate["created_at"]),
            "updated_at": _timestamp(candidate["updated_at"]),
        }
        projection["journey"] = project_voucher_journey(projection)
        return projection

    def _project_revision(
        self, tenant_id: str, revision: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "revision_no": int(revision["revision_no"]),
            "revision_id": str(revision["revision_id"]),
            "candidate_hash": str(revision["candidate_hash"]),
            "recognition_date": revision["recognition_date"].isoformat(),
            "actor_subject_id": str(revision["created_by"]),
            "lines": [self._project_line(tenant_id, line) for line in revision["lines"]],
            "created_at": _timestamp(revision["created_at"]),
        }

    def _project_line(self, tenant_id: str, line: Mapping[str, Any]) -> dict[str, Any]:
        account = self._accounts.get_account(
            tenant_id=tenant_id,
            account_id=str(line["account_id"]),
        )
        return {
            "line_no": int(line["line_no"]),
            "account_code": account["account_code"] if account else "UNKNOWN",
            "account_name": account["name"] if account else "Unavailable account",
            "debit_original": format(Decimal(str(line["debit_original"])), ".4f"),
            "credit_original": format(Decimal(str(line["credit_original"])), ".4f"),
            "source_record_line_ref": str(line["source_record_line_ref"]),
            "description": line["description"],
            "evidence_hash": str(line["evidence_hash"]),
        }


def _draft_lines(value: object) -> tuple[DraftLineInput, ...]:
    if not isinstance(value, list) or not 2 <= len(value) <= 1000:
        raise _invalid("lines must contain 2..1000 items.")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise _invalid("Each line must be an object.")
        debit = _money("debit_original", item.get("debit_original"))
        credit = _money("credit_original", item.get("credit_original"))
        if (debit > 0) == (credit > 0):
            raise _invalid("Each line must contain exactly one debit or credit.")
        result.append(
            DraftLineInput(
                account_code=_code("account_code", item.get("account_code")),
                debit_original=debit,
                credit_original=credit,
                source_record_line_ref=_text(
                    "source_record_line_ref", item.get("source_record_line_ref"), 256
                ),
                evidence_hash=_hash_ref("evidence_hash", item.get("evidence_hash")),
                description=(
                    _text("description", item.get("description"), 1000)
                    if item.get("description") is not None
                    else None
                ),
            )
        )
    debit_total = sum((line.debit_original for line in result), Decimal(0))
    credit_total = sum((line.credit_original for line in result), Decimal(0))
    if debit_total <= 0 or debit_total != credit_total:
        raise _invalid("Voucher lines must be balanced with a positive amount.")
    return tuple(result)


def _require_amount_within_envelope(
    lines: Sequence[VoucherCandidateLineInput], envelope: Mapping[str, Any]
) -> None:
    amount = sum((line.debit_original for line in lines), Decimal(0))
    if amount > Decimal(str(envelope["remaining_amount"])):
        raise _conflict("Voucher amount exceeds the remaining approved amount.")


def _line_semantics(line: VoucherCandidateLineInput) -> dict[str, Any]:
    return {
        "account_id": line.account_id,
        "debit_original": format(line.debit_original, ".4f"),
        "credit_original": format(line.credit_original, ".4f"),
        "source_record_line_ref": line.source_record_line_ref,
        "description": line.description,
        "evidence_hash": line.evidence_hash,
    }


def _rate_publication(fx: Mapping[str, Any]) -> str:
    if fx["mode"] == "SAME_CURRENCY":
        return "SAME_CURRENCY"
    return (
        f"{fx['mode']}:{fx['selected_rate_date']}:"
        f"{fx['base_currency']}/{fx['quote_currency']}"
    )


def _trace(value: object, *, fallback: str) -> dict[str, str]:
    if value is None:
        return {
            "trace_id": fallback,
            "correlation_id": fallback,
            "causation_id": fallback,
        }
    if not isinstance(value, Mapping):
        raise _invalid("trace must be an object.")
    return {
        key: _text(f"trace.{key}", value.get(key), 128)
        for key in ("trace_id", "correlation_id", "causation_id")
    }


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _date(field: str, value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise _invalid(f"{field} must be an ISO date.") from exc


def _aware(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("A timezone-aware datetime is required.")
    return value.astimezone(UTC)


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} must be a positive integer.")
    return value


def _money(field: str, value: object) -> Decimal:
    try:
        admitted = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid(f"{field} must be a canonical amount.") from exc
    if admitted < 0:
        raise _invalid(f"{field} cannot be negative.")
    return admitted


def _project_code(value: object) -> str:
    admitted = str(value or "").strip().upper()
    if len(admitted) != 11:
        raise _invalid("project_code must be an 11-character registration code.")
    return admitted


def _code(field: str, value: object) -> str:
    admitted = str(value or "").strip().upper()
    if not admitted or len(admitted) > 64 or not admitted.replace("_", "").isalnum():
        raise _invalid(f"{field} has invalid code syntax.")
    return admitted


def _text(field: str, value: object, maximum: int) -> str:
    admitted = str(value or "").strip()
    if not admitted or len(admitted) > maximum:
        raise _invalid(f"{field} must contain 1..{maximum} characters.")
    return admitted


def _hash_ref(field: str, value: object) -> str:
    admitted = str(value or "").strip()
    if len(admitted) != 71 or not admitted.startswith("sha256:"):
        raise _invalid(f"{field} must be a SHA-256 hash reference.")
    try:
        int(admitted[7:], 16)
    except ValueError as exc:
        raise _invalid(f"{field} must be a SHA-256 hash reference.") from exc
    return admitted


def _timestamp(value: datetime) -> str:
    admitted = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return admitted.isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> EosBusinessVoucherDraftError:
    return EosBusinessVoucherDraftError(
        "EOS_BUSINESS_VOUCHER_DRAFT_INVALID",
        detail,
        status_code=422,
    )


def _conflict(detail: str) -> EosBusinessVoucherDraftError:
    return EosBusinessVoucherDraftError(
        "EOS_BUSINESS_VOUCHER_DRAFT_CONFLICT",
        detail,
        status_code=409,
    )


__all__ = [
    "CREATE_DRAFT_OPERATION",
    "REVISE_DRAFT_OPERATION",
    "SUBMIT_DRAFT_OPERATION",
    "EosBusinessVoucherDraftError",
    "EosBusinessVoucherDraftService",
]
