from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from .business_proposals import (
    BusinessProposalSubmissionInput,
    EosBusinessProposalError,
    SqlAlchemyEosBusinessProposalRepository,
)
from .scoped_approvals import EosScopedApprovalService, scoped_approval_payload_hash
from .voucher_commands import EosServiceCaller


class EosBusinessProposalLifecycleService:
    """Compose proposal submission with the canonical scoped approval runtime."""

    def __init__(
        self,
        *,
        proposals: SqlAlchemyEosBusinessProposalRepository,
        scoped_approvals: EosScopedApprovalService,
    ) -> None:
        self._proposals = proposals
        self._scoped_approvals = scoped_approvals

    def submit(
        self,
        submission: BusinessProposalSubmissionInput,
        *,
        submitted_at: datetime,
    ) -> dict[str, Any]:
        proposal = self._proposals.submit(submission, submitted_at=submitted_at)
        return self._ensure_approval(proposal)

    def resume(
        self,
        *,
        tenant_id: str,
        proposal_id: str,
        requester_subject_id: str,
        expected_revision: int,
        expected_preview_hash: str,
        selected_approvers: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        proposal = self._proposals.get(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            requester_subject_id=requester_subject_id,
        )
        if proposal is None:
            raise _conflict("Business proposal replay identity was not found")
        if proposal["state"] not in {"SUBMITTED", "APPROVED", "REJECTED"}:
            raise _conflict("Business proposal is not an admitted submission replay")
        if int(proposal.get("submitted_revision_no") or 0) != expected_revision:
            raise _conflict("Business proposal replay revision conflicts")
        if proposal.get("approval_preview_hash") != expected_preview_hash:
            raise _conflict("Business proposal replay preview conflicts")
        persisted_line = proposal.get("approval_line")
        if not isinstance(persisted_line, list) or not _same_selection(
            persisted_line, selected_approvers
        ):
            raise _conflict("Business proposal replay approval line conflicts")
        return self._ensure_approval(proposal)

    def _ensure_approval(self, proposal: Mapping[str, Any]) -> dict[str, Any]:
        payload = _scoped_request(proposal)
        approval = self._scoped_approvals.request_case(
            payload,
            caller=EosServiceCaller(
                "nex-eos-product",
                "nex-eos",
                ("service:call",),
            ),
        )
        case = approval["scoped_approval_case"]
        bound = self._proposals.bind_approval_case(
            tenant_id=proposal["tenant_id"],
            proposal_id=proposal["proposal_id"],
            revision_no=proposal["submitted_revision_no"],
            approval_case_id=case["case_id"],
        )
        return {**bound, "approval_receipt": approval}


def _scoped_request(proposal: Mapping[str, Any]) -> dict[str, Any]:
    revision = proposal["current_revision"]
    revision_no = int(proposal["submitted_revision_no"])
    proposal_id = str(proposal["proposal_id"])
    tenant_id = str(proposal["tenant_id"])
    case_id = _stable_id("case", tenant_id, proposal_id, revision_no)
    operation_id = _stable_id("operation", tenant_id, proposal_id, revision_no)
    envelope_id = _stable_id("envelope", tenant_id, proposal_id, revision_no)
    approval_line = proposal.get("approval_line")
    if not isinstance(approval_line, list) or not approval_line:
        raise _conflict("Submitted business proposal has no admitted approval line")
    subject_hash = semantic_sha256_hash_ref(
        {
            "schema_version": "eos_business_proposal_signoff_subject.v1",
            "tenant_id": tenant_id,
            "proposal_id": proposal_id,
            "revision_no": revision_no,
            "content_hash": revision["content_hash"],
            "attachment_manifest_hash": revision["attachment_manifest_hash"],
            "approval_policy_hash": proposal["approval_policy_hash"],
            "approval_line_hash": proposal["approval_line_hash"],
            "normalization_hash": proposal["normalization_hash"],
        }
    )
    context = {
        "schema_version": "eos_document_signoff_context.v2",
        "envelope_id": envelope_id,
        "approved_document_id": proposal_id,
        "document_revision": revision_no,
        "document_type": revision["document_type"],
        "work_code": revision["work_code"],
        "document_content_hash": revision["content_hash"],
        "attachment_manifest_hash": revision["attachment_manifest_hash"],
        "approved_amount": revision["requested_amount"],
        "approved_currency": revision["original_currency"],
        "tolerance_policy_hash": None,
        "valid_from": revision["valid_from"],
        "valid_until": revision["valid_until"],
        "subject_hash": subject_hash,
        "allowed_project_codes": list(revision["project_codes"]),
    }
    if revision["scope_type"] == "COMPANY":
        context = {
            key: value
            for key, value in context.items()
            if key != "allowed_project_codes"
        }
        context["schema_version"] = "eos_document_signoff_context.v1"
    nominations = [
        {
            "stage_order": item["stage_order"],
            "position_type": item["position_type"],
            "subject_id": item["subject_id"],
            "authority_hash": item["authority_hash"],
            "approval_line_hash": proposal["approval_line_hash"],
        }
        for item in approval_line
    ]
    payload: dict[str, Any] = {
        "schema_version": "eos_scoped_approval_request.v2",
        "tenant_id": tenant_id,
        "business_operation_id": operation_id,
        "idempotency_key": (
            f"business-proposal:{proposal_id}:revision:{revision_no}:signoff"
        ),
        "case": {
            "tenant_id": tenant_id,
            "case_id": case_id,
            "company_id": proposal["company_id"],
            "purpose": "DOCUMENT_SIGNOFF",
            "scope_type": revision["scope_type"],
            "project_ids": list(revision["project_ids"]),
            "subject_ref": (
                f"mybee.business-proposal:{proposal_id}:revision:{revision_no}"
            ),
            "subject_revision": revision_no,
            "subject_hash": subject_hash,
            "requester_subject_id": proposal["requester_subject_id"],
            "approval_policy_id": proposal["approval_policy_id"],
            "correlation_id": f"proposal:{proposal_id}:revision:{revision_no}",
            "causation_id": f"proposal-submit:{proposal_id}:revision:{revision_no}",
            "expires_at": revision["valid_until"],
            "stage_nominations": nominations,
            "document_signoff_context": context,
        },
    }
    payload["payload_hash"] = scoped_approval_payload_hash(payload)
    return payload


def _stable_id(kind: str, tenant_id: str, proposal_id: str, revision_no: int) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/eos/business-proposal/"
            f"{kind}/{tenant_id}/{proposal_id}/{revision_no}",
        )
    )


def _same_selection(
    persisted_line: list[Mapping[str, Any]],
    requested_line: list[Mapping[str, Any]],
) -> bool:
    if len(persisted_line) != len(requested_line):
        return False
    return all(
        int(persisted.get("stage_order", 0)) == index
        and int(requested.get("stage_order", 0)) == index
        and persisted.get("subject_id") == requested.get("subject_id")
        for index, (persisted, requested) in enumerate(
            zip(persisted_line, requested_line, strict=True), start=1
        )
    )


def _conflict(detail: str) -> EosBusinessProposalError:
    return EosBusinessProposalError(
        "BUSINESS_PROPOSAL_CONFLICT",
        detail,
        status_code=409,
    )


__all__ = ["EosBusinessProposalLifecycleService"]
