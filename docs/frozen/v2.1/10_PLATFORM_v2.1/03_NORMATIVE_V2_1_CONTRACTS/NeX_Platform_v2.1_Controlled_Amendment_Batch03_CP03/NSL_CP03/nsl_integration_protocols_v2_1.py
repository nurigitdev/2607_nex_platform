from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Mapping, Any, Literal

Json = Mapping[str, Any]

@dataclass(frozen=True)
class PackageTrustEvidenceV21:
    package_id: str
    package_hash: str
    publisher_id: str
    signing_key_id: str
    verified_at: str
    trust_policy_id: str
    trust_status: Literal["VALID"]
    governance_status: Literal["ACTIVE"]
    governance_decision_ref: str

@dataclass(frozen=True)
class ArtifactAdmissionDecisionV21:
    decision_id: str
    decision: Literal["ADMITTED", "REJECTED"]
    package_id: str
    package_hash: str
    publisher_id: str
    signing_key_id: str
    governance_status: str
    trust_policy_id: str
    package_trust_evidence_ref: str | None
    reason_codes: tuple[str, ...]
    decided_at: str

@dataclass(frozen=True)
class VerifiedSkillArtifactV21:
    skill_id: str
    skill_version: str
    skill_semantic_hash: str
    package_id: str
    package_hash: str
    publisher_id: str
    signing_key_id: str
    runtime_contract_ref: str
    package_trust_evidence: PackageTrustEvidenceV21
    artifact_admission_decision: ArtifactAdmissionDecisionV21

@dataclass(frozen=True)
class ProtectedOperationDescriptorV21:
    tenant_id: str
    agent_execution_id: str
    executable_step_id: str
    business_operation_id: str
    project_ref: str
    capability: str
    operation_class: str
    business_object_type: str
    typed_parameters: Json
    operation_fingerprint: str

@dataclass(frozen=True)
class OperationTrustDecisionV21:
    decision: Literal["ALLOW", "DENY", "REVIEW", "INDETERMINATE"]
    decision_mode: str
    assurance_level: str
    operation_fingerprint: str
    facts_hash: str
    decision_hash: str
    evaluated_at: str
    expires_at: str
    reason_code: str | None = None
    proof_ref: str | None = None

@dataclass(frozen=True)
class ApprovalEvidenceV21:
    tenant_id: str
    nsl_execution_id: str
    business_operation_id: str
    approval_id: str
    approval_request_id: str
    skill_semantic_hash: str
    decision: Literal["APPROVED", "REJECTED"]
    approver_id: str
    decided_at: str
    expires_at: str | None
    payload_hash: str
    write_intent_hash: str
    evidence_integrity: str
    oa_decision_ref: str

@dataclass(frozen=True)
class NSLApprovalResumeV21:
    tenant_id: str
    agent_execution_id: str
    executable_step_id: str
    nsl_execution_id: str
    business_operation_id: str
    approval_request_id: str
    nsl_checkpoint_version: int
    event_id: str
    correlation_id: str
    approval_work_item_ref: str
    approval_evidence_ref: str
    resume_token_ref: str


@dataclass(frozen=True)
class NSLResultSummaryV21:
    nsl_execution_id: str
    business_operation_id: str
    execution_status: str
    commit_state: str | None
    verification_status: str | None
    retry_safety: str | None
    result_ref: str | None
    evidence_refs: tuple[str, ...]

@dataclass(frozen=True)
class StepExecutionOutcomeV21:
    outcome_status: str
    retry_disposition: Literal["RETRY_WITH_BACKOFF","DO_NOT_RETRY","RECONCILE_FIRST","REPLAN_OR_ESCALATE"] | None
    commit_state: str | None
    verification_status: str | None
    result_ref: str | None
    evidence_refs: tuple[str, ...]

@dataclass(frozen=True)
class IdempotencyDecisionV21:
    decision: Literal["NEW","REPLAY_OR_CONTINUE","IDEMPOTENCY_CONFLICT"]
    original_result_ref: str | None
    business_reference: str | None

class NSLIdempotencyStoreV21(Protocol):
    def reserve_or_get(
        self, *, tenant_id: str, business_operation_id: str, write_node_id: str,
        idempotency_key: str, payload_hash: str
    ) -> IdempotencyDecisionV21: ...
    def record_outcome(
        self, *, tenant_id: str, idempotency_key: str, state: str,
        original_result_ref: str | None, provider_transaction_ref: str | None,
        business_reference: str | None
    ) -> None: ...

def classify_idempotency_reentry(*, existing_payload_hash: str | None, new_payload_hash: str) -> Literal["NEW","REPLAY_OR_CONTINUE","IDEMPOTENCY_CONFLICT"]:
    if existing_payload_hash is None:
        return "NEW"
    if existing_payload_hash == new_payload_hash:
        return "REPLAY_OR_CONTINUE"
    return "IDEMPOTENCY_CONFLICT"

def map_nsl_result_to_step_outcome(result: NSLResultSummaryV21) -> StepExecutionOutcomeV21:
    retry_disposition = None
    if result.commit_state == "COMMITTED":
        retry_disposition = "DO_NOT_RETRY"
    elif result.commit_state == "UNKNOWN_COMMIT_STATE":
        retry_disposition = "RECONCILE_FIRST"
    elif result.commit_state == "NOT_COMMITTED" and result.retry_safety == "SAFE_TO_RETRY":
        retry_disposition = "RETRY_WITH_BACKOFF"
    elif result.retry_safety == "UNSAFE_TO_RETRY":
        retry_disposition = "DO_NOT_RETRY"
    return StepExecutionOutcomeV21(
        outcome_status=result.execution_status,
        retry_disposition=retry_disposition,
        commit_state=result.commit_state,
        verification_status=result.verification_status,
        result_ref=result.result_ref,
        evidence_refs=result.evidence_refs,
    )

class SkillArtifactGateway(Protocol):
    def resolve_verified(
        self, *, tenant_id: str, skill_id: str, exact_version: str,
        runtime_contract_ref: str | None = None
    ) -> VerifiedSkillArtifactV21: ...

class NSLRuntimePort(Protocol):
    def execute(self, *, verified_artifact: VerifiedSkillArtifactV21, execution_request: Json) -> Json: ...

class NSLResultMapper(Protocol):
    def to_step_outcome(self, result: NSLResultSummaryV21) -> StepExecutionOutcomeV21: ...

class GovernedWriteExecutionPort(Protocol):
    def execute(
        self, *, write_call_request: Json,
        protected_operation_descriptor: ProtectedOperationDescriptorV21,
        operation_trust_decision: OperationTrustDecisionV21 | None,
        oa_allowed: bool,
        required_assurance_level: str,
    ) -> Json: ...

class NSLSecurityContextResolver(Protocol):
    def resolve_execution_principal(self, *, tenant_id: str, principal_context_ref: str) -> Any: ...
    def resolve_data_policy(self, *, tenant_id: str, data_policy_ref: str) -> Any: ...

_ASSURANCE_ORDER = {"NONE":0, "STANDARD":1, "HIGH":2, "CRITICAL":3}

def governed_write_binding_allows(
    *, oa_allowed: bool,
    descriptor: ProtectedOperationDescriptorV21,
    trust: OperationTrustDecisionV21 | None,
    actual_operation_fingerprint: str,
    required_assurance_level: str,
    now_iso: str | None = None,
) -> bool:
    if not oa_allowed:
        return False
    if trust is None or trust.decision != "ALLOW":
        return False
    if trust.operation_fingerprint != descriptor.operation_fingerprint:
        return False
    if actual_operation_fingerprint != descriptor.operation_fingerprint:
        return False
    if _ASSURANCE_ORDER.get(trust.assurance_level, -1) < _ASSURANCE_ORDER.get(required_assurance_level, 10**6):
        return False
    if trust.decision_mode == "DUMMY_ALWAYS_ALLOW" and _ASSURANCE_ORDER.get(required_assurance_level, 1) > 0:
        return False
    if now_iso is not None and trust.expires_at <= now_iso:
        return False
    return True

def validate_nsl_resume_binding(
    *, bridge: NSLApprovalResumeV21, evidence: ApprovalEvidenceV21,
    expected_payload_hash: str, expected_write_intent_hash: str,
) -> bool:
    return (
        evidence.decision == "APPROVED"
        and bridge.tenant_id == evidence.tenant_id
        and bridge.nsl_execution_id == evidence.nsl_execution_id
        and bridge.business_operation_id == evidence.business_operation_id
        and bridge.approval_request_id == evidence.approval_request_id
        and evidence.payload_hash == expected_payload_hash
        and evidence.write_intent_hash == expected_write_intent_hash
    )

def verified_artifact_is_admitted(artifact: VerifiedSkillArtifactV21) -> bool:
    a = artifact.artifact_admission_decision
    t = artifact.package_trust_evidence
    return (
        a.decision == "ADMITTED"
        and a.governance_status == "ACTIVE"
        and t.trust_status == "VALID"
        and t.governance_status == "ACTIVE"
        and a.package_id == t.package_id == artifact.package_id
        and a.package_hash == t.package_hash == artifact.package_hash
        and a.publisher_id == t.publisher_id == artifact.publisher_id
        and a.signing_key_id == t.signing_key_id == artifact.signing_key_id
    )

# Invariants:
# - SkillExecutionRequest carries principal_context_ref/data_policy_ref; unresolved refs fail closed.
# - RESUME carries non-empty resume_token_ref + approval_evidence_ref.
# - Governed WRITE requires current OA ALLOW and exact trust/actual-operation conformance.
# - Production WRITE admission consumes a typed VerifiedSkillArtifactV21 with current PackageTrustEvidence.


# Step 4 reliability invariants:
# - same IdempotencyKey + same PayloadHash => replay/continue original business effect.
# - same IdempotencyKey + different PayloadHash => IDEMPOTENCY_CONFLICT; Provider WRITE = 0.
# - UNKNOWN_COMMIT_STATE => RECONCILIATION_REQUIRED + RECONCILE_FIRST; no blind WRITE retry.
# - COMMITTED + Verification FAILED/UNKNOWN => DO_NOT_RETRY the same WRITE.
