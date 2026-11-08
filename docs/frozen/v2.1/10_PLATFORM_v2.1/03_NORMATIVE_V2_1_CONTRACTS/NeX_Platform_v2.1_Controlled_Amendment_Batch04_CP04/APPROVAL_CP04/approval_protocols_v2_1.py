from dataclasses import dataclass
from typing import Protocol, Literal, Optional, Mapping, Any

ApprovalDomain = Literal["AGENT_FORMAL", "NSL_WRITE"]
ApprovalDecisionValue = Literal["APPROVE", "REJECT"]

@dataclass(frozen=True)
class ApprovalWorkflowRequest:
    approval_work_item_id: str
    approval_domain: ApprovalDomain
    tenant_id: str
    source_ref: str
    resume_target_ref: str
    binding: Mapping[str, Any]

@dataclass(frozen=True)
class ApprovalWorkflowDecision:
    approval_work_item_id: str
    decision: ApprovalDecisionValue
    decided_by: str
    decision_version: int
    oa_decision_ref: str

@dataclass(frozen=True)
class NSLApprovalResumeBridge:
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

class ApprovalWorkflowProvider(Protocol):
    def create_or_get(self, request: ApprovalWorkflowRequest) -> str: ...
    def submit_decision(self, decision: ApprovalWorkflowDecision) -> None: ...
    def get_status(self, approval_work_item_id: str) -> str: ...

class NSLApprovalResumePublisher(Protocol):
    def publish_resume(self, bridge: NSLApprovalResumeBridge) -> None: ...

class BusinessApprovalAdapter(Protocol):
    def ensure_domain_approval(self, approval_work_item_id: str, business_payload_ref: str) -> str: ...
