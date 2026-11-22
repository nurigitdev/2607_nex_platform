from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .accounting_approval import (
    ACCOUNTING_APPROVAL_SCOPE,
    EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE,
    EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE,
    EOS_SCOPED_APPROVAL_DECISION_TABLE,
)
from .approval_policies import EOS_APPROVAL_POLICY_STAGE_TABLE
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .candidate_review import EOS_CANDIDATE_REVIEW_EVENT_TABLE
from .project_authorization import (
    EosProjectAuthorizationError,
    EosProjectAuthorizationGate,
)
from .scoped_approvals import EOS_SCOPED_APPROVAL_CASE_TABLE
from .voucher_candidates import (
    EOS_VOUCHER_CANDIDATE_REVISION_TABLE,
    EOS_VOUCHER_CANDIDATE_TABLE,
)

ACCOUNTING_POSTING_ADMISSION_OPERATION = "FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION"
ACCOUNTING_POSTING_ADMISSION_REQUEST_SCHEMA = (
    "eos_accounting_posting_admission_request.v1"
)
ACCOUNTING_POSTING_ADMISSION_SCHEMA = "eos_accounting_posting_admission.v1"
DEFAULT_ACCOUNTING_POSTING_ADMISSION_TTL_SECONDS = 30

_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "company_id",
        "expected_candidate_version",
        "expected_candidate_revision",
        "expected_candidate_hash",
        "accounting_approval_evidence_id",
        "correlation_id",
    }
)
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION_HASH = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_HUMAN_PRINCIPAL_PREFIXES = ("agent:", "job:", "service:", "nex-")


class EosAccountingPostingAdmissionError(RuntimeError):
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


class EosAccountingPostingAdmissionService:
    """Admit exact accounting proof without crossing the future Posting UoW."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        authorization_source: AuthorizationSource,
        project_authorizer: EosProjectAuthorizationGate,
        admission_ttl_seconds: int = DEFAULT_ACCOUNTING_POSTING_ADMISSION_TTL_SECONDS,
        clock=None,
    ) -> None:
        if (
            not isinstance(admission_ttl_seconds, int)
            or not 1 <= admission_ttl_seconds <= 300
        ):
            raise ValueError("admission_ttl_seconds must be between 1 and 300")
        self._session_factory = session_factory
        self._authorization_source = authorization_source
        self._project_authorizer = project_authorizer
        self._admission_ttl = timedelta(seconds=admission_ttl_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def admit(self, candidate_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
        request = _admit_request(candidate_id, value)
        before = self._load_snapshot(request)

        authorization = self._fresh_authorization(before)
        project_authorization = self._fresh_project_authorization(
            before,
            correlation_id=request["correlation_id"],
        )
        admitted_at = _aware_datetime("clock", self._clock())

        after = self._load_snapshot(request)
        if before["snapshot_hash"] != after["snapshot_hash"]:
            raise _stale("Accounting proof or Candidate changed during admission")
        return _receipt(
            request=request,
            snapshot=after,
            authorization=authorization,
            project_authorization=project_authorization,
            admitted_at=admitted_at,
            expires_at=admitted_at + self._admission_ttl,
        )

    def require_current_in_session(
        self,
        session: Session,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        admitted = _admit_receipt(receipt)
        now = _aware_datetime("clock", self._clock())
        if admitted["expires_at"] <= now:
            raise EosAccountingPostingAdmissionError(
                "EOS_ACCOUNTING_OA_AUTHORIZATION_STALE",
                "Accounting Posting admission expired before the local transaction",
                status_code=409,
            )
        request = {
            "schema_version": ACCOUNTING_POSTING_ADMISSION_REQUEST_SCHEMA,
            "tenant_id": admitted["tenant_id"],
            "company_id": admitted["company_id"],
            "candidate_id": admitted["candidate_id"],
            "expected_candidate_version": admitted["candidate_version"],
            "expected_candidate_revision": admitted["candidate_revision"],
            "expected_candidate_hash": admitted["candidate_hash"],
            "accounting_approval_evidence_id": admitted[
                "accounting_approval_evidence_id"
            ],
            "correlation_id": admitted["correlation_id"],
        }
        snapshot = _load_snapshot_in_session(session, request=request, lock=True)
        if snapshot["snapshot_hash"] != admitted["snapshot_hash"]:
            raise _stale("Accounting proof or Candidate changed before Posting")
        return dict(receipt)

    def _load_snapshot(self, request: Mapping[str, Any]) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                return _load_snapshot_in_session(session, request=request, lock=False)
        except EosAccountingPostingAdmissionError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable(
                "Accounting Posting admission persistence is unavailable"
            ) from exc

    def _fresh_authorization(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        subject_id = snapshot["approver_subject_id"]
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=snapshot["tenant_id"],
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied("OA denied the current accounting approver") from exc
        except Exception as exc:
            raise _unavailable("OA effective authorization is unavailable") from exc
        return _admit_current_authorization(
            value,
            tenant_id=snapshot["tenant_id"],
            company_id=snapshot["company_id"],
            subject_id=subject_id,
            final_role=snapshot["final_role"],
        )

    def _fresh_project_authorization(
        self,
        snapshot: Mapping[str, Any],
        *,
        correlation_id: str,
    ) -> dict[str, Any]:
        try:
            evidence = self._project_authorizer.authorize(
                tenant_id=snapshot["tenant_id"],
                subject_id=snapshot["approver_subject_id"],
                project_id=snapshot["project_id"],
                action=ACCOUNTING_APPROVAL_SCOPE,
                correlation_id=correlation_id,
                expected_project_code=snapshot["project_code"],
            )
        except EosProjectAuthorizationError as exc:
            if exc.status_code == 403:
                raise _denied("OA denied the exact Project accounting action") from exc
            raise _unavailable("Project authorization is unavailable") from exc
        if evidence.project_status not in {"ACTIVE", "CLOSING"}:
            raise _denied("Project is not eligible for accounting Posting")
        return {
            "decision_ref": evidence.decision_ref,
            "project_code": evidence.project_code,
            "project_role": evidence.project_role,
            "project_status": evidence.project_status,
            "source_version": evidence.source_version,
            "projection_event_hash": evidence.projection_event_hash,
            "authorization_revision_hash": evidence.authorization_revision_hash,
            "decided_at": evidence.decided_at,
        }


def _load_snapshot_in_session(
    session: Session,
    *,
    request: Mapping[str, Any],
    lock: bool,
) -> dict[str, Any]:
    evidence_statement = select(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE).where(
        EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.tenant_id == request["tenant_id"],
        EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.evidence_id
        == request["accounting_approval_evidence_id"],
    )
    if lock:
        evidence_statement = evidence_statement.with_for_update()
    evidence = session.execute(evidence_statement).mappings().one_or_none()
    if evidence is None:
        raise _approval_required("Exact accounting approval evidence was not found")

    case = _one(
        session,
        select(EOS_SCOPED_APPROVAL_CASE_TABLE).where(
            EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id == request["tenant_id"],
            EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == evidence["case_id"],
        ),
    )
    review = _one(
        session,
        select(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE).where(
            EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.c.tenant_id == request["tenant_id"],
            EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.c.case_id == evidence["case_id"],
        ),
    )
    candidate_statement = select(EOS_VOUCHER_CANDIDATE_TABLE).where(
        EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == request["tenant_id"],
        EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == request["candidate_id"],
    )
    if lock:
        candidate_statement = candidate_statement.with_for_update()
    candidate = _one(session, candidate_statement)
    if case is None or review is None or candidate is None:
        raise _approval_required("Accounting proof lineage is incomplete")

    revision = _one(
        session,
        select(EOS_VOUCHER_CANDIDATE_REVISION_TABLE).where(
            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id == request["tenant_id"],
            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.candidate_id
            == request["candidate_id"],
            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.revision_no
            == candidate["current_revision_no"],
        ),
    )
    submitted = _one(
        session,
        select(EOS_CANDIDATE_REVIEW_EVENT_TABLE).where(
            EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.tenant_id == request["tenant_id"],
            EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.approval_case_id == evidence["case_id"],
            EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.transition_kind == "SUBMIT",
        ),
    )
    final_decision = _one(
        session,
        select(EOS_SCOPED_APPROVAL_DECISION_TABLE).where(
            EOS_SCOPED_APPROVAL_DECISION_TABLE.c.tenant_id == request["tenant_id"],
            EOS_SCOPED_APPROVAL_DECISION_TABLE.c.wc_decision_id
            == evidence["wc_final_decision_id"],
        ),
    )
    final_role = session.execute(
        select(EOS_APPROVAL_POLICY_STAGE_TABLE.c.position_type).where(
            EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == request["tenant_id"],
            EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id
            == case["approval_policy_id"],
            EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order == case["stage_count"],
        )
    ).scalar_one_or_none()
    if (
        revision is None
        or submitted is None
        or final_decision is None
        or final_role is None
    ):
        raise _approval_required("Accounting proof lineage is incomplete")

    snapshot = _snapshot(
        request=request,
        evidence=dict(evidence),
        case=case,
        review=review,
        candidate=candidate,
        revision=revision,
        submitted=submitted,
        final_decision=final_decision,
        final_role=str(final_role),
    )
    _require_snapshot(snapshot, request=request)
    snapshot["snapshot_hash"] = _snapshot_hash(snapshot)
    return snapshot


def _snapshot(
    *,
    request: Mapping[str, Any],
    evidence: Mapping[str, Any],
    case: Mapping[str, Any],
    review: Mapping[str, Any],
    candidate: Mapping[str, Any],
    revision: Mapping[str, Any],
    submitted: Mapping[str, Any],
    final_decision: Mapping[str, Any],
    final_role: str,
) -> dict[str, Any]:
    return {
        "tenant_id": str(request["tenant_id"]),
        "company_id": str(candidate["company_id"]),
        "candidate_id": str(candidate["candidate_id"]),
        "candidate_version": int(candidate["version"]),
        "candidate_state": str(candidate["state"]),
        "candidate_revision": int(candidate["current_revision_no"]),
        "candidate_hash": str(revision["candidate_hash"]),
        "project_id": str(candidate["project_id"]),
        "project_code": str(candidate["project_code"]),
        "case_id": str(case["case_id"]),
        "case_company_id": str(case["company_id"]),
        "case_state": str(case["state"]),
        "case_purpose": str(case["purpose"]),
        "case_subject_ref": str(case["subject_ref"]),
        "case_subject_revision": int(case["subject_revision"]),
        "case_subject_hash": str(case["subject_hash"]),
        "requester_subject_id": str(case["requester_id"]),
        "approval_policy_hash": str(case["approval_policy_hash"]),
        "final_role": final_role,
        "review_schema_version": str(review["review_schema_version"]),
        "review_candidate_id": str(review["candidate_id"]),
        "review_candidate_version": review["candidate_version"],
        "review_candidate_revision": int(review["candidate_revision"]),
        "review_candidate_hash": str(review["candidate_hash"]),
        "validation_hash": review["validation_hash"],
        "review_hash": str(review["review_hash"]),
        "candidate_preparer_subject_id": str(review["candidate_preparer_id"]),
        "business_approver_subject_ids": list(review["business_approver_ids"]),
        "document_envelope_hash": str(review["document_envelope_hash"]),
        "fx_rate_set_hash": str(review["fx_rate_set_hash"]),
        "rule_release_hash": str(review["rule_release_hash"]),
        "accounting_period_id": str(review["accounting_period_id"]),
        "submitted_event_id": str(submitted["event_id"]),
        "submitted_transition_kind": str(submitted["transition_kind"]),
        "submitted_to_state": str(submitted["to_state"]),
        "submitted_candidate_version": int(submitted["resulting_version"]),
        "submitted_candidate_revision": int(submitted["candidate_revision"]),
        "submitted_candidate_hash": str(submitted["candidate_hash"]),
        "submitted_validation_hash": submitted["validation_hash"],
        "submitted_review_hash": str(submitted["review_hash"]),
        "accounting_approval_evidence_id": str(evidence["evidence_id"]),
        "evidence_company_id": str(evidence["company_id"]),
        "evidence_candidate_id": str(evidence["candidate_id"]),
        "evidence_candidate_revision": int(evidence["candidate_revision"]),
        "evidence_candidate_hash": str(evidence["candidate_hash"]),
        "evidence_document_envelope_hash": str(evidence["document_envelope_hash"]),
        "evidence_fx_rate_set_hash": str(evidence["fx_rate_set_hash"]),
        "evidence_rule_release_hash": str(evidence["rule_release_hash"]),
        "evidence_accounting_period_id": str(evidence["accounting_period_id"]),
        "approver_subject_id": str(evidence["approver_subject_id"]),
        "evidence_approval_policy_hash": str(evidence["approval_policy_hash"]),
        "wc_final_decision_id": str(evidence["wc_final_decision_id"]),
        "proof_hash": str(evidence["proof_hash"]),
        "final_decision_stage": int(final_decision["stage_order"]),
        "stage_count": int(case["stage_count"]),
        "final_decision": str(final_decision["decision"]),
        "final_decided_by": str(final_decision["decided_by"]),
    }


def _require_snapshot(
    snapshot: Mapping[str, Any], *, request: Mapping[str, Any]
) -> None:
    if snapshot["case_purpose"] != "ACCOUNTING_POSTING":
        raise EosAccountingPostingAdmissionError(
            "EOS_ACCOUNTING_PROOF_PURPOSE_MISMATCH",
            "DOCUMENT_SIGNOFF cannot satisfy ACCOUNTING_POSTING",
            status_code=422,
        )
    if snapshot["case_state"] != "APPROVED" or snapshot["final_decision"] != "APPROVE":
        raise _approval_required("Accounting approval is not final")
    if snapshot["review_schema_version"] != "eos_accounting_review_context.v3":
        raise _stale("Accounting proof lacks authoritative Candidate validation")
    if snapshot["candidate_state"] != "READY_FOR_REVIEW":
        raise _stale("VoucherCandidate is no longer ready for Posting")
    expected = (
        request["tenant_id"],
        request["company_id"],
        request["candidate_id"],
        request["expected_candidate_version"],
        request["expected_candidate_revision"],
        request["expected_candidate_hash"],
    )
    actual = (
        snapshot["tenant_id"],
        snapshot["company_id"],
        snapshot["candidate_id"],
        snapshot["candidate_version"],
        snapshot["candidate_revision"],
        snapshot["candidate_hash"],
    )
    if actual != expected:
        raise _stale("Requested Candidate version, revision, or hash is stale")
    if (
        snapshot["case_company_id"] != snapshot["company_id"]
        or snapshot["evidence_company_id"] != snapshot["company_id"]
        or snapshot["evidence_candidate_id"] != snapshot["candidate_id"]
        or snapshot["review_candidate_id"] != snapshot["candidate_id"]
        or snapshot["case_subject_ref"]
        != f"eos.voucher-candidate:{snapshot['candidate_id']}"
        or snapshot["case_subject_revision"] != snapshot["candidate_revision"]
        or snapshot["case_subject_hash"] != snapshot["candidate_hash"]
        or snapshot["review_candidate_revision"] != snapshot["candidate_revision"]
        or snapshot["review_candidate_hash"] != snapshot["candidate_hash"]
        or snapshot["evidence_candidate_revision"] != snapshot["candidate_revision"]
        or snapshot["evidence_candidate_hash"] != snapshot["candidate_hash"]
        or snapshot["submitted_candidate_revision"] != snapshot["candidate_revision"]
        or snapshot["submitted_candidate_hash"] != snapshot["candidate_hash"]
        or snapshot["submitted_candidate_version"] != snapshot["candidate_version"]
        or snapshot["submitted_transition_kind"] != "SUBMIT"
        or snapshot["submitted_to_state"] != "READY_FOR_REVIEW"
    ):
        raise _stale("Candidate review and proof lineage is stale")
    if (
        snapshot["review_candidate_version"] is None
        or int(snapshot["review_candidate_version"]) + 1
        != snapshot["candidate_version"]
        or not _HASH_REF.fullmatch(str(snapshot["validation_hash"]))
        or snapshot["submitted_validation_hash"] != snapshot["validation_hash"]
        or snapshot["submitted_review_hash"] != snapshot["review_hash"]
    ):
        raise _stale("Candidate validation or submission lineage is stale")
    if (
        snapshot["evidence_document_envelope_hash"]
        != snapshot["document_envelope_hash"]
        or snapshot["evidence_fx_rate_set_hash"] != snapshot["fx_rate_set_hash"]
        or snapshot["evidence_rule_release_hash"] != snapshot["rule_release_hash"]
        or snapshot["evidence_accounting_period_id"] != snapshot["accounting_period_id"]
        or snapshot["evidence_approval_policy_hash"] != snapshot["approval_policy_hash"]
        or snapshot["final_decision_stage"] != snapshot["stage_count"]
        or snapshot["final_decided_by"] != snapshot["approver_subject_id"]
    ):
        raise _stale("Accounting proof does not match the admitted review")
    approver = snapshot["approver_subject_id"]
    if approver.lower().startswith(_HUMAN_PRINCIPAL_PREFIXES):
        raise _sod_denied("Accounting approval requires a Human principal")
    if approver in {
        snapshot["requester_subject_id"],
        snapshot["candidate_preparer_subject_id"],
    }:
        raise _sod_denied("Requester or Candidate preparer cannot approve Posting")
    business_approvers = snapshot["business_approver_subject_ids"]
    if not isinstance(business_approvers, list) or any(
        not isinstance(item, str) or not item for item in business_approvers
    ):
        raise _stale("Business approver lineage is malformed")
    if len(business_approvers) == 1 and business_approvers[0] == approver:
        raise _sod_denied("Sole business approver cannot approve accounting Posting")


def _admit_current_authorization(
    value: object,
    *,
    tenant_id: str,
    company_id: str,
    subject_id: str,
    final_role: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _denied("OA accounting authorization is malformed")
    if (
        value.get("active") is not True
        or value.get("tenant_id") != tenant_id
        or value.get("subject_id") != subject_id
    ):
        raise _denied("Active OA Human authorization is required")
    scopes = _string_set("scopes", value.get("scopes"))
    roles = {item.lower() for item in _string_set("roles", value.get("roles"))}
    if ACCOUNTING_APPROVAL_SCOPE not in scopes:
        raise _denied("Current finance:journal:approve scope is required")
    if final_role.lower() not in roles:
        raise _denied("Current OA role does not match the final approval stage")
    company_ids = value.get("company_ids")
    if company_ids is not None and company_id not in _string_set(
        "company_ids", company_ids
    ):
        raise _denied("OA company scope does not include the accounting company")
    revision = value.get("revision_hash")
    if not isinstance(revision, str) or _REVISION_HASH.fullmatch(revision) is None:
        raise _denied("OA authorization revision is invalid")
    revision_hash = revision if revision.startswith("sha256:") else f"sha256:{revision}"
    decision_ref = value.get("decision_ref") or (
        f"oa-authz:{revision_hash.removeprefix('sha256:')}"
    )
    return {
        "decision_ref": _scoped_id("decision_ref", decision_ref),
        "revision_hash": revision_hash,
    }


def _receipt(
    *,
    request: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    authorization: Mapping[str, Any],
    project_authorization: Mapping[str, Any],
    admitted_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    semantics = {
        "schema_version": ACCOUNTING_POSTING_ADMISSION_SCHEMA,
        "operation_id": ACCOUNTING_POSTING_ADMISSION_OPERATION,
        "admission_id": str(
            uuid5(
                NAMESPACE_URL,
                "https://nex-platform.local/eos/accounting-posting-admission/"
                f"{snapshot['tenant_id']}/{snapshot['accounting_approval_evidence_id']}/"
                f"{snapshot['candidate_version']}/{authorization['revision_hash']}",
            )
        ),
        "tenant_id": snapshot["tenant_id"],
        "company_id": snapshot["company_id"],
        "candidate_id": snapshot["candidate_id"],
        "candidate_version": snapshot["candidate_version"],
        "candidate_revision": snapshot["candidate_revision"],
        "candidate_hash": snapshot["candidate_hash"],
        "project_id": snapshot["project_id"],
        "project_code": snapshot["project_code"],
        "accounting_approval_evidence_id": snapshot["accounting_approval_evidence_id"],
        "accounting_proof_hash": snapshot["proof_hash"],
        "approval_case_id": snapshot["case_id"],
        "approver_subject_id": snapshot["approver_subject_id"],
        "validation_hash": snapshot["validation_hash"],
        "review_hash": snapshot["review_hash"],
        "submitted_event_id": snapshot["submitted_event_id"],
        "fresh_oa_decision_ref": authorization["decision_ref"],
        "fresh_oa_revision_hash": authorization["revision_hash"],
        "fresh_project_authorization": dict(project_authorization),
        "snapshot_hash": snapshot["snapshot_hash"],
        "correlation_id": request["correlation_id"],
        "admitted_at": admitted_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    return {**semantics, "admission_hash": semantic_sha256_hash_ref(semantics)}


def _admit_request(candidate_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REQUEST_FIELDS:
        raise _invalid("Posting admission request fields do not match the contract")
    if value.get("schema_version") != ACCOUNTING_POSTING_ADMISSION_REQUEST_SCHEMA:
        raise _invalid("Posting admission request schema_version is invalid")
    return {
        "schema_version": ACCOUNTING_POSTING_ADMISSION_REQUEST_SCHEMA,
        "tenant_id": _scoped_id("tenant_id", value.get("tenant_id")),
        "company_id": _uuid("company_id", value.get("company_id")),
        "candidate_id": _uuid("candidate_id", candidate_id),
        "expected_candidate_version": _positive_int(
            "expected_candidate_version", value.get("expected_candidate_version")
        ),
        "expected_candidate_revision": _positive_int(
            "expected_candidate_revision", value.get("expected_candidate_revision")
        ),
        "expected_candidate_hash": _hash_ref(
            "expected_candidate_hash", value.get("expected_candidate_hash")
        ),
        "accounting_approval_evidence_id": _uuid(
            "accounting_approval_evidence_id",
            value.get("accounting_approval_evidence_id"),
        ),
        "correlation_id": _scoped_id("correlation_id", value.get("correlation_id")),
    }


def _admit_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != ACCOUNTING_POSTING_ADMISSION_SCHEMA
    ):
        raise _invalid("Accounting Posting admission receipt is invalid")
    admission_hash = value.get("admission_hash")
    semantics = {key: item for key, item in value.items() if key != "admission_hash"}
    if not isinstance(
        admission_hash, str
    ) or admission_hash != semantic_sha256_hash_ref(semantics):
        raise _invalid("Accounting Posting admission receipt hash is invalid")
    return {
        **dict(value),
        "tenant_id": _scoped_id("tenant_id", value.get("tenant_id")),
        "company_id": _uuid("company_id", value.get("company_id")),
        "candidate_id": _uuid("candidate_id", value.get("candidate_id")),
        "candidate_version": _positive_int(
            "candidate_version", value.get("candidate_version")
        ),
        "candidate_revision": _positive_int(
            "candidate_revision", value.get("candidate_revision")
        ),
        "candidate_hash": _hash_ref("candidate_hash", value.get("candidate_hash")),
        "accounting_approval_evidence_id": _uuid(
            "accounting_approval_evidence_id",
            value.get("accounting_approval_evidence_id"),
        ),
        "correlation_id": _scoped_id("correlation_id", value.get("correlation_id")),
        "snapshot_hash": _hash_ref("snapshot_hash", value.get("snapshot_hash")),
        "expires_at": _datetime("expires_at", value.get("expires_at")),
    }


def _snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {
            "schema_version": "eos_accounting_posting_snapshot.v1",
            **{
                key: snapshot[key] for key in sorted(snapshot) if key != "snapshot_hash"
            },
        }
    )


def _one(session: Session, statement) -> dict[str, Any] | None:
    row = session.execute(statement).mappings().one_or_none()
    return dict(row) if row is not None else None


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(f"{field_name} must be a UUID") from exc


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{field_name} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be a positive integer") from exc
    if normalized < 1 or str(normalized) != str(value):
        raise _invalid(f"{field_name} must be a positive integer")
    return normalized


def _hash_ref(field_name: str, value: object) -> str:
    normalized = str(value) if isinstance(value, str) else ""
    if _HASH_REF.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} must be a sha256 hash reference")
    return normalized


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if isinstance(value, str) else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} has invalid stable-reference syntax")
    return normalized


def _datetime(field_name: str, value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field_name} must be an ISO-8601 datetime") from exc
    return _aware_datetime(field_name, parsed)


def _aware_datetime(field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _string_set(field_name: str, value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise _denied(f"OA {field_name} is malformed")
    normalized = {item for item in value if isinstance(item, str) and item}
    if len(normalized) != len(value):
        raise _denied(f"OA {field_name} is malformed")
    return normalized


def _invalid(detail: str) -> EosAccountingPostingAdmissionError:
    return EosAccountingPostingAdmissionError(
        "EOS_ACCOUNTING_POSTING_ADMISSION_INVALID",
        detail,
        status_code=422,
    )


def _approval_required(detail: str) -> EosAccountingPostingAdmissionError:
    return EosAccountingPostingAdmissionError(
        "EOS_ACCOUNTING_APPROVAL_REQUIRED",
        detail,
        status_code=422,
    )


def _sod_denied(detail: str) -> EosAccountingPostingAdmissionError:
    return EosAccountingPostingAdmissionError(
        "EOS_ACCOUNTING_SOD_DENIED",
        detail,
        status_code=403,
    )


def _denied(detail: str) -> EosAccountingPostingAdmissionError:
    return EosAccountingPostingAdmissionError(
        "EOS_ACCOUNTING_OA_SCOPE_DENIED",
        detail,
        status_code=403,
    )


def _stale(detail: str) -> EosAccountingPostingAdmissionError:
    return EosAccountingPostingAdmissionError(
        "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE",
        detail,
        status_code=409,
    )


def _unavailable(detail: str) -> EosAccountingPostingAdmissionError:
    return EosAccountingPostingAdmissionError(
        "EOS_ACCOUNTING_POSTING_ADMISSION_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )


__all__ = (
    "ACCOUNTING_POSTING_ADMISSION_OPERATION",
    "ACCOUNTING_POSTING_ADMISSION_REQUEST_SCHEMA",
    "ACCOUNTING_POSTING_ADMISSION_SCHEMA",
    "DEFAULT_ACCOUNTING_POSTING_ADMISSION_TTL_SECONDS",
    "EosAccountingPostingAdmissionError",
    "EosAccountingPostingAdmissionService",
)
