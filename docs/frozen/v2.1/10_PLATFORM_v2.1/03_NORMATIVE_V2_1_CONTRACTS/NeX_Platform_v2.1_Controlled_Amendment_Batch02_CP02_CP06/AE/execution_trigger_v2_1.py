from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional, Protocol

AgentType = Literal["IA", "CA", "PA", "EA"]
TriggerSource = Literal["PROMPT", "CLAIMED_WORKITEM"]

@dataclass(frozen=True)
class ExecutionTriggerV21:
    trigger_id: str
    source_type: TriggerSource
    source_ref: str
    tenant_id: str
    agent_type: AgentType
    agent_id: str
    project_id: str
    correlation_id: str
    received_at: str
    work_item_ref: Optional[str] = None
    claim_ref: Optional[str] = None
    claim_generation: Optional[int] = None
    assignment_ref: Optional[str] = None
    requester_ref: Optional[str] = None
    causation_id: Optional[str] = None

class AgentExecutionTriggerSinkV21(Protocol):
    async def start_execution(self, trigger: ExecutionTriggerV21) -> str:
        """Idempotently create/return AgentExecution for a valid trigger."""
        ...
