from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def project_proposal_journey(proposal: Mapping[str, Any]) -> dict[str, Any]:
    state = str(proposal.get("state", "")).strip().upper()
    approval_line = proposal.get("approval_line")
    stage_count = len(approval_line) if isinstance(approval_line, Sequence) else 0
    if state == "DRAFT":
        statuses = ("CURRENT", "UPCOMING", "UPCOMING")
        current_stage = "PROPOSAL_DRAFT"
        terminal = False
    elif state == "SUBMITTED":
        statuses = ("COMPLETED", "CURRENT", "UPCOMING")
        current_stage = "BUSINESS_APPROVAL"
        terminal = False
    elif state == "APPROVED":
        statuses = ("COMPLETED", "COMPLETED", "AVAILABLE")
        current_stage = "VOUCHER_PREPARATION"
        terminal = False
    elif state == "REJECTED":
        statuses = ("COMPLETED", "REJECTED", "BLOCKED")
        current_stage = "BUSINESS_APPROVAL"
        terminal = True
    elif state == "WITHDRAWN":
        statuses = ("COMPLETED", "CANCELLED", "BLOCKED")
        current_stage = "BUSINESS_APPROVAL"
        terminal = True
    else:
        raise ValueError("Unsupported BusinessProposal state")
    return {
        "schema_version": "eos_business_journey.v1",
        "journey_kind": "BUSINESS_PROPOSAL",
        "current_stage": current_stage,
        "terminal": terminal,
        "approval_stage_count": stage_count,
        "steps": _steps(
            ("PROPOSAL_DRAFT", "BUSINESS_APPROVAL", "VOUCHER_PREPARATION"),
            ("품의서 작성", "품의 결재", "전표 작성"),
            statuses,
        ),
    }


def project_voucher_journey(candidate: Mapping[str, Any]) -> dict[str, Any]:
    state = str(candidate.get("state", "")).strip().upper()
    if state == "DRAFT":
        statuses = ("CURRENT", "UPCOMING", "UPCOMING")
        current_stage = "VOUCHER_REVIEW"
        terminal = False
    elif state == "READY_FOR_REVIEW":
        statuses = ("COMPLETED", "CURRENT", "UPCOMING")
        current_stage = "ACCOUNTING_APPROVAL"
        terminal = False
    elif state == "RETURNED_FOR_CORRECTION":
        statuses = ("CURRENT", "RETURNED", "BLOCKED")
        current_stage = "VOUCHER_REVIEW"
        terminal = False
    elif state == "POSTED":
        statuses = ("COMPLETED", "COMPLETED", "COMPLETED")
        current_stage = "JOURNAL_POSTING"
        terminal = True
    else:
        raise ValueError("Unsupported VoucherCandidate state")
    return {
        "schema_version": "eos_business_journey.v1",
        "journey_kind": "ACCOUNTING_VOUCHER",
        "current_stage": current_stage,
        "terminal": terminal,
        "approval_stage_count": None,
        "steps": _steps(
            ("VOUCHER_REVIEW", "ACCOUNTING_APPROVAL", "JOURNAL_POSTING"),
            ("전표 검토", "회계 결재", "총계정원장 반영"),
            statuses,
        ),
    }


def _steps(
    codes: Sequence[str], labels: Sequence[str], statuses: Sequence[str]
) -> list[dict[str, object]]:
    return [
        {"order": order, "code": code, "label": label, "status": status}
        for order, (code, label, status) in enumerate(
            zip(codes, labels, statuses, strict=True), start=1
        )
    ]


__all__ = ["project_proposal_journey", "project_voucher_journey"]
