from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast, get_type_hints

from nex_runtime.semantic_hashes import validate_hash_ref

from nex_ae_api.platform_approval_evidence import (
    validate_platform_approval_evidence,
)


class PlatformApprovalEvidenceSource(Protocol):
    def get(
        self, *, tenant_id: str, approval_request_id: str
    ) -> Mapping[str, Any] | None: ...


class WcApprovalAuthoritySource(Protocol):
    def resolve(
        self, *, tenant_id: str, approval_work_item_ref: str
    ) -> Mapping[str, Any]: ...


class OaApprovalAuthoritySource(Protocol):
    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, Any]: ...


class NslApprovalEvidenceLike(Protocol):
    tenant_id: str
    execution_id: str
    business_operation_id: str
    approval_id: str
    approval_request_id: str
    skill_semantic_hash: str
    decision: Any
    approver_id: str
    decided_at: datetime
    expires_at: datetime | None
    payload_hash: str
    write_intent_hash: str
    evidence_integrity: str


class NslApprovalEvidenceProjectionError(ValueError):
    pass


def project_nsl_approval_evidence(
    platform_evidence: Mapping[str, Any],
    *,
    approval_evidence_type: type[Any],
) -> Any:
    """Project immutable Platform evidence through the admitted NSL public type."""

    record = validate_platform_approval_evidence(platform_evidence)
    try:
        decision_type = get_type_hints(approval_evidence_type)["decision"]
        decision = decision_type(_NSL_DECISIONS[record["decision"]])
        projected = approval_evidence_type(
            tenant_id=record["tenant_id"],
            execution_id=record["nsl_execution_id"],
            business_operation_id=record["business_operation_id"],
            approval_id=record["approval_id"],
            approval_request_id=record["approval_request_id"],
            skill_semantic_hash=record["skill_semantic_hash"],
            decision=decision,
            approver_id=record["approver_id"],
            decided_at=_utc(record["decided_at"]),
            expires_at=(
                _utc(record["expires_at"]) if record["expires_at"] is not None else None
            ),
            payload_hash=record["payload_hash"],
            write_intent_hash=record["write_intent_hash"],
            evidence_integrity=record["evidence_integrity"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NslApprovalEvidenceProjectionError(
            "The admitted NSL ApprovalEvidence type is incompatible."
        ) from exc
    if _evidence_data(projected) != _projected_data(record):
        raise NslApprovalEvidenceProjectionError(
            "The admitted NSL ApprovalEvidence projection changed its bindings."
        )
    return projected


class PlatformApprovalEvidenceVerifier:
    """NSL verifier for Platform provenance and current authority evidence."""

    def __init__(
        self,
        *,
        evidence_source: PlatformApprovalEvidenceSource,
        wc_source: WcApprovalAuthoritySource,
        oa_source: OaApprovalAuthoritySource,
    ) -> None:
        self._evidence_source = evidence_source
        self._wc_source = wc_source
        self._oa_source = oa_source

    def verify(self, evidence: object) -> bool:
        try:
            projected = _evidence_data(evidence)
            canonical = self._evidence_source.get(
                tenant_id=projected["tenant_id"],
                approval_request_id=projected["approval_request_id"],
            )
            if canonical is None:
                return False
            record = validate_platform_approval_evidence(canonical)
            if projected != _projected_data(record):
                return False
            authority = self._wc_source.resolve(
                tenant_id=record["tenant_id"],
                approval_work_item_ref=record["approval_work_item_ref"],
            )
            work_item = _mapping(authority, "work_item")
            decision = _mapping(authority, "decision")
            if not _wc_authority_matches(record, work_item, decision):
                return False
            current = self._oa_source.effective_authorization(
                tenant_id=record["tenant_id"],
                subject_id=record["approver_id"],
            )
            return _oa_authority_matches(record, current)
        except Exception:  # noqa: BLE001 - NSL verifier must fail closed.
            return False


class PersistedApprovalEventAuthoritySource:
    """Project immutable WC decision authority from its admitted AE evidence."""

    def __init__(self, evidence_source: Any) -> None:
        if not callable(getattr(evidence_source, "get_by_work_item_ref", None)):
            raise TypeError("approval evidence work-item lookup is unavailable")
        self._evidence_source = evidence_source

    def resolve(
        self, *, tenant_id: str, approval_work_item_ref: str
    ) -> Mapping[str, Any]:
        value = self._evidence_source.get_by_work_item_ref(
            tenant_id=tenant_id,
            approval_work_item_ref=approval_work_item_ref,
        )
        if value is None:
            raise NslApprovalEvidenceProjectionError(
                "Persisted approval event authority is unavailable."
            )
        record = validate_platform_approval_evidence(value)
        state = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}[record["decision"]]
        return {
            "work_item": {
                "tenant_id": record["tenant_id"],
                "approval_work_item_id": record["approval_work_item_ref"],
                "approval_domain": "NSL_WRITE",
                "approval_provider_type": "NSL",
                "source_ref": record["approval_request_id"],
                "approval_target_ref": record["approval_request_id"],
                "agent_execution_id": record["agent_execution_id"],
                "executable_step_id": record["executable_step_id"],
                "nsl_execution_id": record["nsl_execution_id"],
                "business_operation_id": record["business_operation_id"],
                "approval_request_id": record["approval_request_id"],
                "protected_request_ref": record["protected_request_ref"],
                "state": state,
            },
            "decision": {
                "tenant_id": record["tenant_id"],
                "approval_work_item_id": record["approval_work_item_ref"],
                "decision": record["decision"],
                "decided_by": record["approver_id"],
                "decided_at": record["decided_at"],
                "oa_decision_ref": record["oa_decision_ref"],
                "authorized_by_oa": True,
            },
        }


def _wc_authority_matches(
    record: Mapping[str, Any],
    work_item: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> bool:
    terminal_state = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}[record["decision"]]
    item_fields = {
        "tenant_id": record["tenant_id"],
        "approval_work_item_id": record["approval_work_item_ref"],
        "approval_domain": "NSL_WRITE",
        "approval_provider_type": "NSL",
        "source_ref": record["approval_request_id"],
        "approval_target_ref": record["approval_request_id"],
        "agent_execution_id": record["agent_execution_id"],
        "executable_step_id": record["executable_step_id"],
        "nsl_execution_id": record["nsl_execution_id"],
        "business_operation_id": record["business_operation_id"],
        "approval_request_id": record["approval_request_id"],
        "protected_request_ref": record["protected_request_ref"],
        "state": terminal_state,
    }
    decision_fields = {
        "tenant_id": record["tenant_id"],
        "approval_work_item_id": record["approval_work_item_ref"],
        "decision": record["decision"],
        "decided_by": record["approver_id"],
        "decided_at": record["decided_at"],
        "oa_decision_ref": record["oa_decision_ref"],
        "authorized_by_oa": True,
    }
    return _contains(work_item, item_fields) and _contains(decision, decision_fields)


def _oa_authority_matches(
    record: Mapping[str, Any], authorization: Mapping[str, Any]
) -> bool:
    if authorization.get("active") is not True:
        return False
    scopes = authorization.get("scopes")
    if (
        not isinstance(scopes, Sequence)
        or isinstance(scopes, (str, bytes))
        or "approval:decide" not in scopes
    ):
        return False
    revision_hash = authorization.get("revision_hash")
    try:
        revision_hash = validate_hash_ref(
            revision_hash
            if str(revision_hash).startswith("sha256:")
            else f"sha256:{revision_hash}"
        )
    except ValueError:
        return False
    decision_ref = authorization.get("decision_ref")
    if decision_ref is None:
        decision_ref = f"oa-authz:{revision_hash.removeprefix('sha256:')}"
    return decision_ref == record["oa_decision_ref"]


def _evidence_data(value: object) -> dict[str, Any]:
    try:
        evidence = cast(NslApprovalEvidenceLike, value)
        data = {
            "tenant_id": evidence.tenant_id,
            "execution_id": evidence.execution_id,
            "business_operation_id": evidence.business_operation_id,
            "approval_id": evidence.approval_id,
            "approval_request_id": evidence.approval_request_id,
            "skill_semantic_hash": evidence.skill_semantic_hash,
            "decision": evidence.decision.value,
            "approver_id": evidence.approver_id,
            "decided_at": _time(evidence.decided_at),
            "expires_at": (
                _time(evidence.expires_at) if evidence.expires_at is not None else None
            ),
            "payload_hash": evidence.payload_hash,
            "write_intent_hash": evidence.write_intent_hash,
            "evidence_integrity": evidence.evidence_integrity,
        }
    except (AttributeError, TypeError, ValueError) as exc:
        raise NslApprovalEvidenceProjectionError(
            "NSL ApprovalEvidence is malformed."
        ) from exc
    return data


def _projected_data(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": record["tenant_id"],
        "execution_id": record["nsl_execution_id"],
        "business_operation_id": record["business_operation_id"],
        "approval_id": record["approval_id"],
        "approval_request_id": record["approval_request_id"],
        "skill_semantic_hash": record["skill_semantic_hash"],
        "decision": _NSL_DECISIONS[record["decision"]],
        "approver_id": record["approver_id"],
        "decided_at": record["decided_at"],
        "expires_at": record["expires_at"],
        "payload_hash": record["payload_hash"],
        "write_intent_hash": record["write_intent_hash"],
        "evidence_integrity": record["evidence_integrity"],
    }


def _mapping(value: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    candidate = value.get(field) if isinstance(value, Mapping) else None
    if not isinstance(candidate, Mapping):
        raise NslApprovalEvidenceProjectionError(
            f"Current WC {field} evidence is unavailable."
        )
    return candidate


def _contains(value: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(
        value.get(field) == expected_value for field, expected_value in expected.items()
    )


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _time(value: object) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise NslApprovalEvidenceProjectionError("NSL evidence timestamp is invalid.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


_NSL_DECISIONS = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}
