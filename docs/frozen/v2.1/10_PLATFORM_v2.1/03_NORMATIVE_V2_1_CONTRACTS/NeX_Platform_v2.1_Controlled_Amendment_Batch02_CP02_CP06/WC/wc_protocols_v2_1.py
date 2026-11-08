from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Sequence, Mapping, Any

Json = Mapping[str, Any]

@dataclass(frozen=True)
class RoutingContextV21:
    tenant_id: str
    work_item_id: str
    required_capability: str
    organization_scope_ref: str | None
    project_scope_ref: str | None
    required_agent_type: str | None  # CA | PA | EA
    risk_level: str

@dataclass(frozen=True)
class CandidateV21:
    candidate_type: str  # HUMAN | AGENT | EXTERNAL_AGENT
    candidate_ref: str
    eligible: bool
    reason_codes: tuple[str, ...]
    agent_type: str | None = None  # CA | PA | EA when candidate_type=AGENT

class ClaimRepositoryV21(Protocol):
    async def claim(self, *, tenant_id: str, work_item_id: str, claimant_ref: str, claimant_agent_type: str | None, required_agent_type: str | None, worker_ref: str | None, lease_seconds: int) -> Json | None: ...
    async def heartbeat(self, claim_id: str, lease_token: str, lease_seconds: int) -> bool: ...
    async def release(self, claim_id: str, lease_token: str, reason: str) -> bool: ...

# Invariant: for AGENT work, successful atomic claim materializes actual assignment;
# WorkItem existence alone never starts CA/PA/EA AgentExecution.


@dataclass(frozen=True)
class ClaimExecutionHandoffV21:
    handoff_id: str
    tenant_id: str
    work_item_ref: str
    claim_ref: str
    claim_generation: int
    claimant_agent_ref: str
    claimant_agent_type: str  # CA | PA | EA
    project_id: str
    assignment_ref: str
    correlation_id: str
    occurred_at: str
    causation_id: str | None = None

class ClaimExecutionHandoffPublisherV21(Protocol):
    async def publish_claimed_work(self, handoff: ClaimExecutionHandoffV21) -> None:
        """Publish only after successful atomic claim + assignment materialization commit."""
        ...


@dataclass(frozen=True)
class WorkResultSubmittedV21:
    event_id: str
    tenant_id: str
    work_item_id: str
    result_id: str
    revision_no: int
    result_type: str
    technical_outcome: str
    business_outcome: str
    submitted_by_type: str
    submitted_by_ref: str
    resume_match_ref: str
    correlation_id: str
    occurred_at: str
    result_schema_ref: str | None = None
    source_execution_ref: str | None = None
    claim_ref: str | None = None
    claim_generation: int | None = None
    assignment_ref: str | None = None
    causation_id: str | None = None

class WorkResultRepositoryV21(Protocol):
    async def submit_result(self, *, result: Json, idempotency_key: str, expected_work_version: int) -> Json: ...

class WorkResultEventPublisherV21(Protocol):
    async def publish_result_submitted(self, event: WorkResultSubmittedV21) -> None:
        """Publish from WC outbox only after WorkResult + WorkItem RESULT_SUBMITTED commit."""
        ...

# Invariants:
# - required_agent_type is copied from WorkItem.routing_target into RoutingContext/Decision.
# - When required_agent_type is non-null, eligible AGENT candidates and successful claimant must match it.
# - For PA, project_scope_ref/project_ref are mandatory.
# - WORK_RESULT_SUBMITTED.event_id is deduplicated by AE. resume_match_ref == work_item_id.
# - Parent Agent resumes only after result contract validation; Claim/Assignment does not resume parent.
