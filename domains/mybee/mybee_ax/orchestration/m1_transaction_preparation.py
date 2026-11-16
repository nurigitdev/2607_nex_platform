"""Authority-backed, restart-safe M1 transaction preparation orchestration."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.business_context import (
    BusinessContextValidationError,
    validate_business_request_context,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from ..domain.documents import (
    BusinessProposalProjectRef,
    build_business_proposal_form,
)
from ..integrations.nex_business_approval_client import NexBusinessApprovalClient
from ..integrations.nex_voucher_candidate_client import (
    NexVoucherCandidateClient,
    VoucherCandidateLine,
    build_voucher_candidate_draft,
)

M1_PREPARATION_SCHEMA_VERSION = "nex.mybee.m1-transaction-preparation.v1"
M1_PREPARATION_REGISTRY_SCHEMA_VERSION = (
    "nex.mybee.m1-transaction-preparation-registry.v1"
)
M1_PREPARATION_ADAPTER_ID = "MYBEE.M1.AUTHORITATIVE_TRANSACTION_PREPARATION"
DEFAULT_M1_TRANSACTION_PREPARATION_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "config/m1_transaction_preparation_registry.v1.json"
)
_REQUIRED_OPERATIONS = (
    "BUSINESS.DOCUMENT_APPROVED.GET",
    "FINANCE.ACCOUNTING_APPROVAL.REQUEST",
    "FINANCE.VOUCHER_CANDIDATE.CREATE_V2",
    "FINANCE.VOUCHER_CANDIDATE.VALIDATE",
    "FINANCE.VOUCHER_CANDIDATE.REVIEW_GET",
    "FINANCE.VOUCHER_POSTING.ADMIT",
)


class M1PreparationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class M1PreparationRegistration:
    adapter_id: str
    adapter_version: str
    implementation_ref: str
    operations: tuple[str, ...]
    debit_semantic_key: str
    credit_semantic_key: str
    source_kind: str
    business_work_code: str
    registry_hash: str

    @property
    def source_identity(self) -> str:
        return (
            f"mybee:m1-preparation:{self.adapter_id}:"
            f"{self.adapter_version}:{self.registry_hash}"
        )


@dataclass(frozen=True)
class M1PreparationAuthority:
    tenant_id: str
    requester_subject_id: str
    company_id: str
    company_code: str
    company_selector_kind: str
    company_selector_value: str
    company_version: int
    company_evidence_hash: str
    functional_currency: str
    primary_project_id: str
    primary_project_code: str
    project_refs: tuple[Mapping[str, Any], ...] = field(repr=False)
    project_authorizations: tuple[Mapping[str, Any], ...] = field(repr=False)
    debit_account_id: str
    debit_semantic_key: str
    debit_account_evidence_hash: str
    credit_account_id: str
    credit_semantic_key: str
    credit_account_evidence_hash: str
    business_approval_policy_id: str
    business_approval_policy_version: int
    business_approval_policy_hash: str
    accounting_approval_policy_id: str
    accounting_approval_policy_version: int
    accounting_approval_policy_hash: str
    project_authorization_ref: str
    project_authorization_revision_hash: str
    authority_effective_at: datetime

    def projection(self) -> dict[str, Any]:
        value = {
            "schema_version": "nex.mybee.m1-preparation-authority.v1",
            "tenant_id": self.tenant_id,
            "requester_subject_id": self.requester_subject_id,
            "company_id": self.company_id,
            "company_code": self.company_code,
            "company_selector_kind": self.company_selector_kind,
            "company_selector_value": self.company_selector_value,
            "company_version": self.company_version,
            "company_evidence_hash": self.company_evidence_hash,
            "functional_currency": self.functional_currency,
            "primary_project_id": self.primary_project_id,
            "primary_project_code": self.primary_project_code,
            "project_refs": [dict(item) for item in self.project_refs],
            "project_authorizations": [
                dict(item) for item in self.project_authorizations
            ],
            "debit_account_id": self.debit_account_id,
            "debit_semantic_key": self.debit_semantic_key,
            "debit_account_evidence_hash": self.debit_account_evidence_hash,
            "credit_account_id": self.credit_account_id,
            "credit_semantic_key": self.credit_semantic_key,
            "credit_account_evidence_hash": self.credit_account_evidence_hash,
            "business_approval_policy_id": self.business_approval_policy_id,
            "business_approval_policy_version": self.business_approval_policy_version,
            "business_approval_policy_hash": self.business_approval_policy_hash,
            "accounting_approval_policy_id": self.accounting_approval_policy_id,
            "accounting_approval_policy_version": (
                self.accounting_approval_policy_version
            ),
            "accounting_approval_policy_hash": self.accounting_approval_policy_hash,
            "project_authorization_ref": self.project_authorization_ref,
            "project_authorization_revision_hash": (
                self.project_authorization_revision_hash
            ),
            "authority_effective_at": _timestamp(self.authority_effective_at),
        }
        value["authority_hash"] = semantic_sha256_hash_ref(value)
        return value


@dataclass(frozen=True)
class M1TransactionPreparationAdapter:
    registration: M1PreparationRegistration
    business_approvals: NexBusinessApprovalClient = field(repr=False)
    voucher_candidates: NexVoucherCandidateClient = field(repr=False)

    def begin_proposal(
        self,
        *,
        business_request_context: Mapping[str, Any],
        business_context_hash: str,
        authority: M1PreparationAuthority,
        parent_execution_id: str,
    ) -> Mapping[str, Any]:
        context = _context(business_request_context, business_context_hash)
        admitted_authority = _authority(
            authority,
            context=context,
            registration=self.registration,
        )
        identities = _identities(
            tenant_id=authority.tenant_id,
            context_hash=context["context_hash"],
            parent_execution_id=parent_execution_id,
        )
        proposal = _proposal(context, authority, identities=identities)
        receipt = self.business_approvals.submit(
            proposal,
            business_operation_id=identities["proposal_operation_id"],
            idempotency_key=identities["proposal_idempotency_key"],
            case_id=identities["proposal_case_id"],
            approval_policy_id=authority.business_approval_policy_id,
            correlation_id=parent_execution_id,
            causation_id=context["source_prompt_ref"],
            expires_at=_aware(authority.authority_effective_at) + timedelta(days=7),
        )
        return _checkpoint(
            stage="WAITING_BUSINESS_APPROVAL",
            context=context,
            authority=admitted_authority,
            identities=identities,
            references={
                "proposal_subject_ref": proposal.subject_ref,
                "proposal_subject_hash": proposal.approval_subject_hash,
                "business_approval_case_id": receipt["scoped_approval_case"]["case_id"],
                "business_approval_work_item_id": receipt["wc_publication"][
                    "work_item"
                ]["work_item_id"],
            },
            adapter=self.registration,
        )

    def continue_after_business_approval(
        self,
        *,
        business_request_context: Mapping[str, Any],
        business_context_hash: str,
        authority: M1PreparationAuthority,
        parent_execution_id: str,
        envelope_id: str,
    ) -> Mapping[str, Any]:
        context = _context(business_request_context, business_context_hash)
        admitted_authority = _authority(
            authority,
            context=context,
            registration=self.registration,
        )
        identities = _identities(
            tenant_id=authority.tenant_id,
            context_hash=context["context_hash"],
            parent_execution_id=parent_execution_id,
        )
        now = _aware(authority.authority_effective_at)
        proposal = _proposal(context, authority, identities=identities)
        envelope = self.business_approvals.get_approved_document(
            proposal,
            envelope_id=envelope_id,
        )
        draft = _draft(
            context,
            authority,
            envelope=envelope,
            identities=identities,
            registration=self.registration,
        )
        created = self.voucher_candidates.create(
            draft,
            business_operation_id=identities["candidate_operation_id"],
            idempotency_key=identities["candidate_idempotency_key"],
            trace_id=parent_execution_id,
            correlation_id=parent_execution_id,
            causation_id=identities["proposal_case_id"],
        )
        validation = self.voucher_candidates.validate(draft, created, as_of=now)
        review = self.voucher_candidates.submit_for_review(
            draft,
            created,
            validation,
            business_operation_id=identities["review_operation_id"],
            idempotency_key=identities["review_idempotency_key"],
            case_id=identities["review_case_id"],
            approval_policy_id=authority.accounting_approval_policy_id,
            correlation_id=parent_execution_id,
            causation_id=identities["candidate_operation_id"],
            expires_at=now + timedelta(days=7),
        )
        return _checkpoint(
            stage="WAITING_ACCOUNTING_APPROVAL",
            context=context,
            authority=admitted_authority,
            identities=identities,
            references={
                "approved_document_envelope_id": envelope["envelope_id"],
                "business_approval_proof_id": envelope["business_approval_proof_id"],
                "candidate_id": created["candidate_ref"]["id"],
                "candidate_version": validation["candidate_version"],
                "candidate_revision": validation["revision_ref"]["revision_no"],
                "candidate_hash": validation["revision_ref"]["hash"],
                "validation_hash": validation["validation_hash"],
                "accounting_approval_case_id": review["scoped_approval_case"][
                    "case_id"
                ],
                "accounting_approval_work_item_id": review["wc_publication"][
                    "work_item"
                ]["work_item_id"],
            },
            adapter=self.registration,
        )

    def continue_after_accounting_approval(
        self,
        *,
        business_request_context: Mapping[str, Any],
        business_context_hash: str,
        authority: M1PreparationAuthority,
        parent_execution_id: str,
        candidate_id: str,
        accounting_approval_evidence_id: str,
    ) -> Mapping[str, Any]:
        context = _context(business_request_context, business_context_hash)
        admitted_authority = _authority(
            authority,
            context=context,
            registration=self.registration,
        )
        identities = _identities(
            tenant_id=authority.tenant_id,
            context_hash=context["context_hash"],
            parent_execution_id=parent_execution_id,
        )
        review = self.voucher_candidates.get_review(
            tenant_id=authority.tenant_id,
            subject_id=authority.requester_subject_id,
            candidate_id=candidate_id,
        )
        events = review.get("events", ())
        submitted = next(
            (
                item
                for item in events
                if isinstance(item, Mapping) and item.get("transition_kind") == "SUBMIT"
            ),
            None,
        )
        if submitted is None:
            raise M1PreparationError(
                "M1_ACCOUNTING_REVIEW_NOT_SUBMITTED",
                "VoucherCandidate lacks its immutable accounting review submission.",
            )
        admission = self.voucher_candidates.admit_posting(
            tenant_id=authority.tenant_id,
            subject_id=authority.requester_subject_id,
            company_id=authority.company_id,
            candidate_id=candidate_id,
            expected_candidate_version=review["candidate_version"],
            expected_candidate_revision=review["current_revision_no"],
            expected_candidate_hash=submitted["candidate_hash"],
            accounting_approval_evidence_id=accounting_approval_evidence_id,
            correlation_id=parent_execution_id,
        )
        return _checkpoint(
            stage="READY_FOR_D04",
            context=context,
            authority=admitted_authority,
            identities=identities,
            references={
                "candidate_id": admission["candidate_id"],
                "candidate_version": admission["candidate_version"],
                "candidate_revision": admission["candidate_revision"],
                "candidate_hash": admission["candidate_hash"],
                "accounting_approval_evidence_id": admission[
                    "accounting_approval_evidence_id"
                ],
                "accounting_proof_hash": admission["accounting_proof_hash"],
                "posting_admission_id": admission["admission_id"],
                "posting_admission_hash": admission["admission_hash"],
                "posting_admission_expires_at": admission["expires_at"],
            },
            adapter=self.registration,
        )


def load_m1_transaction_preparation_registration(
    path: Path = DEFAULT_M1_TRANSACTION_PREPARATION_REGISTRY,
) -> M1PreparationRegistration:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M1PreparationError(
            "M1_PREPARATION_REGISTRY_UNAVAILABLE",
            "M1 transaction preparation registry is unavailable.",
        ) from exc
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "adapter_id",
        "adapter_version",
        "implementation_ref",
        "operations",
        "account_policy",
        "source_kind",
        "business_work_code",
        "registry_hash",
    }:
        raise _invalid("M1 transaction preparation registry fields are invalid.")
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "registry_hash"}
    )
    if (
        value.get("schema_version") != M1_PREPARATION_REGISTRY_SCHEMA_VERSION
        or value.get("adapter_id") != M1_PREPARATION_ADAPTER_ID
        or tuple(value.get("operations", ())) != _REQUIRED_OPERATIONS
        or value.get("registry_hash") != expected_hash
    ):
        raise _invalid("M1 transaction preparation registry admission failed.")
    policy = value.get("account_policy")
    if not isinstance(policy, Mapping) or set(policy) != {
        "debit_semantic_key",
        "credit_semantic_key",
    }:
        raise _invalid("M1 transaction preparation account policy is invalid.")
    return M1PreparationRegistration(
        adapter_id=str(value["adapter_id"]),
        adapter_version=_text("adapter_version", value["adapter_version"]),
        implementation_ref=_text("implementation_ref", value["implementation_ref"]),
        operations=tuple(str(item) for item in value["operations"]),
        debit_semantic_key=_text("debit_semantic_key", policy["debit_semantic_key"]),
        credit_semantic_key=_text("credit_semantic_key", policy["credit_semantic_key"]),
        source_kind=_text("source_kind", value["source_kind"]),
        business_work_code=_text("business_work_code", value["business_work_code"]),
        registry_hash=expected_hash,
    )


def _context(value: Mapping[str, Any], expected_hash: str) -> dict[str, Any]:
    try:
        context = validate_business_request_context(value)
    except BusinessContextValidationError as exc:
        raise _invalid(exc.detail) from exc
    if expected_hash != context["context_hash"]:
        raise _conflict("Business context hash differs from the admitted context.")
    return context


def _authority(
    value: M1PreparationAuthority,
    *,
    context: Mapping[str, Any],
    registration: M1PreparationRegistration,
) -> Mapping[str, Any]:
    if not isinstance(value, M1PreparationAuthority):
        raise _invalid("M1 preparation authority type is invalid.")
    projection = value.projection()
    try:
        uuid.UUID(value.company_id)
        uuid.UUID(value.primary_project_id)
        uuid.UUID(value.debit_account_id)
        uuid.UUID(value.credit_account_id)
        uuid.UUID(value.business_approval_policy_id)
        uuid.UUID(value.accounting_approval_policy_id)
        validate_hash_ref(value.debit_account_evidence_hash)
        validate_hash_ref(value.credit_account_evidence_hash)
        validate_hash_ref(value.company_evidence_hash)
        validate_hash_ref(value.business_approval_policy_hash)
        validate_hash_ref(value.accounting_approval_policy_hash)
        validate_hash_ref(value.project_authorization_revision_hash)
        _aware(value.authority_effective_at)
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid("M1 preparation authority identity is invalid.") from exc
    requested = {str(item["project_code"]) for item in context["requested_allocation"]}
    projects = tuple(dict(item) for item in value.project_refs)
    authorizations = tuple(dict(item) for item in value.project_authorizations)
    if (
        not projects
        or not authorizations
        or value.primary_project_code not in requested
        or {str(item.get("project_code")) for item in projects} != requested
        or {str(item.get("project_code")) for item in authorizations} != requested
        or any(
            set(item) != {"project_id", "project_code", "project_version"}
            or str(item["project_code"]) not in requested
            for item in projects
        )
        or value.company_selector_kind != context["company_selector"]["kind"]
        or value.company_selector_value != context["company_selector"]["value"]
        or value.debit_semantic_key != registration.debit_semantic_key
        or value.credit_semantic_key != registration.credit_semantic_key
        or not _is_positive_int(value.company_version)
        or not _is_positive_int(value.business_approval_policy_version)
        or not _is_positive_int(value.accounting_approval_policy_version)
        or any(not _valid_project_ref(item) for item in projects)
        or any(not _valid_project_authorization(item) for item in authorizations)
    ):
        raise _conflict("EOS authority does not match the admitted business context.")
    return MappingProxyType(projection)


def _identities(*, tenant_id: str, context_hash: str, parent_execution_id: str):
    try:
        uuid.UUID(parent_execution_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid("Parent execution identity is invalid.") from exc
    validate_hash_ref(context_hash)
    seed = f"{tenant_id}/{parent_execution_id}"

    def identity(kind: str) -> str:
        return str(
            uuid5(NAMESPACE_URL, f"https://nex-platform.local/mybee/m1/{kind}/{seed}")
        )

    return {
        "proposal_id": identity("proposal"),
        "proposal_operation_id": identity("proposal-operation"),
        "proposal_case_id": identity("proposal-case"),
        "proposal_idempotency_key": f"m1-proposal:{parent_execution_id}",
        "candidate_operation_id": identity("candidate-operation"),
        "candidate_idempotency_key": f"m1-candidate:{parent_execution_id}",
        "review_operation_id": identity("review-operation"),
        "review_case_id": identity("review-case"),
        "review_idempotency_key": f"m1-review:{parent_execution_id}",
    }


def _proposal(context, authority, *, identities):
    project_refs = tuple(
        BusinessProposalProjectRef(
            project_id=str(item["project_id"]),
            project_code=str(item["project_code"]),
        )
        for item in authority.project_refs
    )
    transaction = context["transaction"]
    return build_business_proposal_form(
        tenant_id=authority.tenant_id,
        proposal_id=identities["proposal_id"],
        revision=int(context["document"]["subject_revision"]),
        company_id=authority.company_id,
        title=str(context["document"]["subject_ref"]),
        purpose=str(transaction["description"]),
        business_justification=(
            f"Counterparty: {transaction['counterparty_selector']}"
        ),
        scope_type="PROJECT" if len(project_refs) == 1 else "PROJECT_SET",
        project_refs=project_refs,
        requested_amount=Decimal(str(transaction["amount"])),
        currency=str(transaction["currency"]),
        requester_subject_id=authority.requester_subject_id,
        valid_from=datetime.combine(
            date.fromisoformat(str(transaction["recognition_date"])),
            datetime.min.time(),
            tzinfo=UTC,
        ),
    )


def _draft(context, authority, *, envelope, identities, registration):
    transaction = context["transaction"]
    amount = Decimal(str(transaction["amount"]))
    return build_voucher_candidate_draft(
        tenant_id=authority.tenant_id,
        company_id=authority.company_id,
        preparer_subject_id=authority.requester_subject_id,
        project_id=authority.primary_project_id,
        project_code=authority.primary_project_code,
        approved_document=envelope,
        source_kind=registration.source_kind,
        source_record_ref=f"mybee.m1:{identities['proposal_id']}",
        business_work_code=registration.business_work_code,
        transaction_currency=str(transaction["currency"]),
        recognition_date=date.fromisoformat(str(transaction["recognition_date"])),
        lines=(
            VoucherCandidateLine(
                account_id=authority.debit_account_id,
                debit_original=amount,
                credit_original=Decimal(0),
                source_record_line_ref="m1-expense-line",
                description=str(transaction["description"]),
                evidence_hash=authority.debit_account_evidence_hash,
            ),
            VoucherCandidateLine(
                account_id=authority.credit_account_id,
                debit_original=Decimal(0),
                credit_original=amount,
                source_record_line_ref="m1-payable-line",
                description=str(transaction["counterparty_selector"]),
                evidence_hash=authority.credit_account_evidence_hash,
            ),
        ),
    )


def _checkpoint(*, stage, context, authority, identities, references, adapter):
    semantics = {
        "schema_version": M1_PREPARATION_SCHEMA_VERSION,
        "stage": stage,
        "business_context_hash": context["context_hash"],
        "authority_hash": authority["authority_hash"],
        "adapter_identity": adapter.source_identity,
        "identities": dict(identities),
        "references": dict(references),
    }
    return MappingProxyType(
        {**semantics, "preparation_hash": semantic_sha256_hash_ref(semantics)}
    )


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("M1 preparation clock must be timezone-aware.")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _aware(value).isoformat().replace("+00:00", "Z")


def _is_positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _valid_project_ref(value: Mapping[str, Any]) -> bool:
    try:
        uuid.UUID(str(value["project_id"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return (
        set(value) == {"project_id", "project_code", "project_version"}
        and isinstance(value.get("project_code"), str)
        and bool(str(value["project_code"]).strip())
        and _is_positive_int(value.get("project_version"))
    )


def _valid_project_authorization(value: Mapping[str, Any]) -> bool:
    if set(value) != {
        "project_code",
        "decision_ref",
        "revision_hash",
        "source_version",
    }:
        return False
    try:
        validate_hash_ref(value["revision_hash"])
    except (TypeError, ValueError):
        return False
    return (
        isinstance(value.get("project_code"), str)
        and bool(str(value["project_code"]).strip())
        and isinstance(value.get("decision_ref"), str)
        and bool(str(value["decision_ref"]).strip())
        and _is_positive_int(value.get("source_version"))
    )


def _text(field_name: str, value: object) -> str:
    normalized = str(value).strip() if isinstance(value, str) else ""
    if not normalized or normalized != value or len(normalized) > 512:
        raise _invalid(f"M1 preparation {field_name} is invalid.")
    return normalized


def _invalid(detail: str) -> M1PreparationError:
    return M1PreparationError("M1_PREPARATION_INVALID", detail)


def _conflict(detail: str) -> M1PreparationError:
    return M1PreparationError("M1_PREPARATION_SEMANTIC_CONFLICT", detail)
