from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .accounts import SqlAlchemyEosAccountRepository
from .accounting_approval import SqlAlchemyAccountingReviewContextRepository
from .scoped_approvals import SqlAlchemyEosScopedApprovalRepository
from .voucher_candidates import SqlAlchemyEosVoucherCandidateRepository


ACCOUNTING_DOCUMENT_PROJECTION_SCHEMA = "eos_accounting_document_projection.v1"
_CANDIDATE_REF_PREFIX = "eos.voucher-candidate:"
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class EosAccountingDisplayError(Exception):
    error_code: str
    detail: str
    status_code: int = 422
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class EosAccountingDisplayService:
    """Projects one exact VoucherCandidate revision for authorized review UIs."""

    def __init__(
        self,
        *,
        scoped_approvals: SqlAlchemyEosScopedApprovalRepository,
        accounting_reviews: SqlAlchemyAccountingReviewContextRepository,
        candidates: SqlAlchemyEosVoucherCandidateRepository,
        accounts: SqlAlchemyEosAccountRepository,
    ) -> None:
        self._scoped_approvals = scoped_approvals
        self._accounting_reviews = accounting_reviews
        self._candidates = candidates
        self._accounts = accounts

    def project_case(self, *, tenant_id: str, case_id: str) -> dict[str, Any]:
        tenant = _text("tenant_id", tenant_id, 128)
        admitted_case_id = _uuid("case_id", case_id)
        scoped_case = self._scoped_approvals.get_case(
            tenant_id=tenant,
            case_id=admitted_case_id,
        )
        if scoped_case is None:
            raise _not_found("Accounting approval case was not found.")
        if scoped_case.get("purpose") != "ACCOUNTING_POSTING":
            raise _conflict("Approval case is not an accounting posting review.")
        subject_ref = str(scoped_case.get("subject_ref") or "")
        if not subject_ref.startswith(_CANDIDATE_REF_PREFIX):
            raise _conflict("Accounting approval subject is not a VoucherCandidate.")
        candidate_id = _uuid(
            "candidate_id",
            subject_ref.removeprefix(_CANDIDATE_REF_PREFIX),
        )
        review = self._accounting_reviews.get(
            tenant_id=tenant,
            case_id=admitted_case_id,
        )
        if review is None:
            raise _conflict("Accounting review context is unavailable.")
        if (
            str(review.get("candidate_id")) != candidate_id
            or review.get("candidate_revision") != scoped_case.get("subject_revision")
            or review.get("candidate_hash") != scoped_case.get("subject_hash")
        ):
            raise _conflict("Accounting case and review candidate lineage differ.")
        return self._project_candidate(
            tenant_id=tenant,
            candidate_id=candidate_id,
            expected_revision=scoped_case["subject_revision"],
            expected_hash=scoped_case["subject_hash"],
            case_id=admitted_case_id,
            approval_state=str(scoped_case["state"]),
            requester_subject_id=str(scoped_case["requester_ref"]["id"]),
        )

    def project_candidate(
        self,
        *,
        tenant_id: str,
        candidate_id: str,
        expected_revision: int,
        expected_hash: str,
    ) -> dict[str, Any]:
        return self._project_candidate(
            tenant_id=_text("tenant_id", tenant_id, 128),
            candidate_id=_uuid("candidate_id", candidate_id),
            expected_revision=_positive_int("expected_revision", expected_revision),
            expected_hash=_hash_ref("expected_hash", expected_hash),
            case_id=None,
            approval_state=None,
            requester_subject_id=None,
        )

    def _project_candidate(
        self,
        *,
        tenant_id: str,
        candidate_id: str,
        expected_revision: int,
        expected_hash: str,
        case_id: str | None,
        approval_state: str | None,
        requester_subject_id: str | None,
    ) -> dict[str, Any]:
        candidate = self._candidates.get(
            tenant_id=tenant_id,
            candidate_id=candidate_id,
        )
        if candidate is None:
            raise _not_found("VoucherCandidate was not found.")
        revision = candidate.get("revision")
        if not isinstance(revision, Mapping):
            raise _conflict("VoucherCandidate revision is unavailable.")
        if (
            candidate.get("current_revision_no") != expected_revision
            or revision.get("revision_no") != expected_revision
            or revision.get("candidate_hash") != expected_hash
        ):
            raise _conflict("VoucherCandidate revision differs from approval lineage.")

        currency = str(candidate["transaction_currency"])
        lines = []
        debit_total = Decimal("0")
        credit_total = Decimal("0")
        for source in candidate.get("lines", ()):
            if not isinstance(source, Mapping):
                raise _conflict("VoucherCandidate line is invalid.")
            account = self._accounts.get_account(
                tenant_id=tenant_id,
                account_id=str(source["account_id"]),
            )
            if account is None:
                raise _conflict("VoucherCandidate account identity is unavailable.")
            debit = Decimal(str(source["debit_original"]))
            credit = Decimal(str(source["credit_original"]))
            debit_total += debit
            credit_total += credit
            lines.append(
                {
                    "line_no": int(source["line_no"]),
                    "account_code": str(account["account_code"]),
                    "account_name": str(account["name"]),
                    "description": source.get("description"),
                    "debit": _money(debit),
                    "credit": _money(credit),
                    "currency": currency,
                }
            )
        if not lines:
            raise _conflict("VoucherCandidate has no accounting lines.")
        difference = debit_total - credit_total
        return {
            "schema_version": ACCOUNTING_DOCUMENT_PROJECTION_SCHEMA,
            "tenant_id": tenant_id,
            "candidate_id": candidate_id,
            "candidate_revision": expected_revision,
            "candidate_hash": expected_hash,
            "company_id": str(candidate["company_id"]),
            "project_code": str(candidate["project_code"]),
            "approved_document_ref": (
                "eos.approved-document-envelope:"
                f"{candidate['document_envelope_id']}"
            ),
            "recognition_date": candidate["recognition_date"].isoformat(),
            "currency": currency,
            "requester_subject_id": (
                requester_subject_id or str(candidate["preparer_subject_id"])
            ),
            "approval_case_id": case_id,
            "approval_state": approval_state,
            "lines": lines,
            "totals": {
                "debit": _money(debit_total),
                "credit": _money(credit_total),
                "difference": _money(difference),
                "balanced": difference == 0,
            },
        }


def _text(field: str, value: object, maximum: int) -> str:
    admitted = str(value).strip() if value is not None else ""
    if not admitted or len(admitted) > maximum:
        raise _invalid(f"{field} is invalid.")
    return admitted


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field} is invalid.") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} is invalid.")
    return value


def _hash_ref(field: str, value: object) -> str:
    admitted = str(value).strip() if value is not None else ""
    if _HASH_REF.fullmatch(admitted) is None:
        raise _invalid(f"{field} is invalid.")
    return admitted


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")), "f")


def _invalid(detail: str) -> EosAccountingDisplayError:
    return EosAccountingDisplayError(
        "EOS_ACCOUNTING_DISPLAY_INVALID",
        detail,
        status_code=422,
    )


def _not_found(detail: str) -> EosAccountingDisplayError:
    return EosAccountingDisplayError(
        "EOS_ACCOUNTING_DISPLAY_NOT_FOUND",
        detail,
        status_code=404,
    )


def _conflict(detail: str) -> EosAccountingDisplayError:
    return EosAccountingDisplayError(
        "EOS_ACCOUNTING_DISPLAY_LINEAGE_CONFLICT",
        detail,
        status_code=409,
    )
