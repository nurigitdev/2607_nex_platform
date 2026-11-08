from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from nex_ae_api.nsl_approval_evidence import (
    PlatformApprovalEvidenceSource,
    project_nsl_approval_evidence,
)
from nex_ae_api.nsl_approval_requests import canonical_approval_request_data
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from nex_ae_api.platform_approval_evidence import (
    validate_platform_approval_evidence,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim


class NslApprovalResumeAuthoritySource(Protocol):
    def resolve(self, claim: RuntimeJobClaim) -> Mapping[str, Any]: ...


class ProtectedApprovalRequestSource(Protocol):
    def load_request(
        self, *, tenant_id: str, approval_request_id: str
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True)
class NslApprovalResumeIntegrationError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class NslApprovalResumeInvocation:
    runtime_job_id: str
    claim_id: str
    nsl_execution_id: str
    business_operation_id: str
    checkpoint_version: int
    approval_request_id: str
    resume_token: Any
    outcome: Any


class NslApprovalResumeIntegration:
    """Assemble persisted Platform authority for the admitted NSL resume API."""

    def __init__(
        self,
        *,
        authority_source: NslApprovalResumeAuthoritySource,
        request_source: ProtectedApprovalRequestSource,
        evidence_source: PlatformApprovalEvidenceSource,
        public_api: NslV02PublicApiAdapter,
    ) -> None:
        if not isinstance(public_api, NslV02PublicApiAdapter):
            raise _invalid("NSL approval resume requires the admitted public API.")
        self._authority_source = authority_source
        self._request_source = request_source
        self._evidence_source = evidence_source
        self._public_api = public_api

    async def resume(
        self,
        claim: RuntimeJobClaim,
        *,
        skill: Any,
        request: Any,
        checkpoint_port: Any,
        verifier: Any,
        clock: Any,
        runtime_clock: Any | None = None,
    ) -> NslApprovalResumeInvocation:
        authority = _authority(self._authority_source.resolve(claim))
        protected_request = self._request_source.load_request(
            tenant_id=authority["tenant_id"],
            approval_request_id=authority["approval_request_id"],
        )
        if protected_request is None:
            raise _missing("Protected NSL ApprovalRequest is unavailable.")
        approval_request = canonical_approval_request_data(
            _ApprovalRequestSnapshot(protected_request)
        )
        platform_evidence = self._evidence_source.get(
            tenant_id=authority["tenant_id"],
            approval_request_id=authority["approval_request_id"],
        )
        if platform_evidence is None:
            raise _missing("Platform ApprovalEvidence is unavailable.")
        evidence = validate_platform_approval_evidence(platform_evidence)
        _require_exact_lineage(authority, approval_request, evidence)

        projected = project_nsl_approval_evidence(
            evidence,
            approval_evidence_type=self._public_api.approval_evidence,
        )
        token = _resume_token(self._public_api, authority, projected)
        coordinator = _coordinator(self._public_api)
        claim_id = authority["runtime_job_id"]
        outcome = await coordinator.resume(
            token=token,
            skill=skill,
            request=request,
            approval_id=approval_request["approval_id"],
            write_node_id=approval_request["write_node_id"],
            current_write_intent_hash=approval_request["write_intent_hash"],
            current_payload_hash=approval_request["payload_hash"],
            claim_id=claim_id,
            checkpoint_port=checkpoint_port,
            verifier=verifier,
            clock=clock,
            runtime_clock=runtime_clock,
        )
        return NslApprovalResumeInvocation(
            runtime_job_id=authority["runtime_job_id"],
            claim_id=claim_id,
            nsl_execution_id=authority["nsl_execution_id"],
            business_operation_id=authority["business_operation_id"],
            checkpoint_version=authority["checkpoint_version"],
            approval_request_id=authority["approval_request_id"],
            resume_token=token,
            outcome=outcome,
        )


@dataclass(frozen=True)
class _ApprovalRequestSnapshot:
    value: Mapping[str, Any]

    def to_data(self) -> dict[str, Any]:
        return dict(self.value)


def _authority(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("NSL approval resume authority must be an object.")
    result = dict(value)
    if result.get("schema_version") != "ae_nsl_approval_resume_authority.v1":
        raise _invalid("NSL approval resume authority schema is invalid.")
    for field in (
        "tenant_id",
        "runtime_job_id",
        "agent_execution_id",
        "executable_step_id",
        "approval_request_id",
        "approval_work_item_ref",
        "nsl_execution_id",
        "business_operation_id",
        "evidence_integrity",
        "approval_evidence_ref",
        "resume_token_ref",
    ):
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            raise _invalid(f"NSL approval resume authority {field} is invalid.")
        result[field] = value.strip()
    checkpoint_version = result.get("checkpoint_version")
    if (
        not isinstance(checkpoint_version, int)
        or isinstance(checkpoint_version, bool)
        or checkpoint_version < 1
    ):
        raise _invalid("NSL approval checkpoint version is invalid.")
    return result


def _require_exact_lineage(
    authority: Mapping[str, Any],
    approval_request: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    expected_request = {
        "tenant_id": authority["tenant_id"],
        "execution_id": authority["nsl_execution_id"],
        "business_operation_id": authority["business_operation_id"],
        "approval_request_id": authority["approval_request_id"],
    }
    expected_evidence = {
        "tenant_id": authority["tenant_id"],
        "agent_execution_id": authority["agent_execution_id"],
        "executable_step_id": authority["executable_step_id"],
        "nsl_execution_id": authority["nsl_execution_id"],
        "business_operation_id": authority["business_operation_id"],
        "approval_request_id": authority["approval_request_id"],
        "approval_work_item_ref": authority["approval_work_item_ref"],
        "evidence_integrity": authority["evidence_integrity"],
    }
    if any(approval_request.get(key) != value for key, value in expected_request.items()):
        raise _invalid("Protected ApprovalRequest lineage differs from resume authority.")
    if any(evidence.get(key) != value for key, value in expected_evidence.items()):
        raise _invalid("Platform ApprovalEvidence lineage differs from resume authority.")
    shared = (
        ("approval_id", "approval_id"),
        ("skill_semantic_hash", "skill_semantic_hash"),
        ("payload_hash", "payload_hash"),
        ("write_intent_hash", "write_intent_hash"),
    )
    if any(approval_request[left] != evidence[right] for left, right in shared):
        raise _invalid("ApprovalRequest and ApprovalEvidence bindings differ.")
    if authority["approval_evidence_ref"] != (
        f"ae-approval-evidence:{authority['approval_request_id']}"
    ) or authority["resume_token_ref"] != (
        f"ae-nsl-resume:{authority['evidence_integrity']}"
    ):
        raise _invalid("NSL approval resume references are invalid.")


def _resume_token(
    public_api: NslV02PublicApiAdapter,
    authority: Mapping[str, Any],
    evidence: Any,
) -> Any:
    try:
        token = public_api.resume_token(
            execution_id=authority["nsl_execution_id"],
            business_operation_id=authority["business_operation_id"],
            checkpoint_version=authority["checkpoint_version"],
            approval_evidence=evidence,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid("The admitted NSL ResumeToken type is incompatible.") from exc
    if (
        getattr(token, "execution_id", None) != authority["nsl_execution_id"]
        or getattr(token, "business_operation_id", None)
        != authority["business_operation_id"]
        or getattr(token, "checkpoint_version", None)
        != authority["checkpoint_version"]
        or getattr(token, "approval_evidence", None) is not evidence
    ):
        raise _invalid("NSL ResumeToken changed persisted resume authority.")
    return token


def _coordinator(public_api: NslV02PublicApiAdapter) -> Any:
    try:
        coordinator = public_api.approval_resume_coordinator()
    except (TypeError, ValueError) as exc:
        raise _invalid("The admitted NSL ApprovalResumeCoordinator is incompatible.") from exc
    if not callable(getattr(coordinator, "resume", None)):
        raise _invalid("The admitted NSL ApprovalResumeCoordinator is incompatible.")
    return coordinator


def _invalid(detail: str) -> NslApprovalResumeIntegrationError:
    return NslApprovalResumeIntegrationError(
        "ae.nsl_approval_resume_integration_invalid", detail
    )


def _missing(detail: str) -> NslApprovalResumeIntegrationError:
    return NslApprovalResumeIntegrationError(
        "ae.nsl_approval_resume_integration_authority_missing", detail
    )
