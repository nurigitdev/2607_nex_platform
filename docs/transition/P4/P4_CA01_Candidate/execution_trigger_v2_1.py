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
    project_id: Optional[str]
    correlation_id: str
    received_at: str
    work_item_ref: Optional[str] = None
    claim_ref: Optional[str] = None
    claim_generation: Optional[int] = None
    assignment_ref: Optional[str] = None
    requester_ref: Optional[str] = None
    causation_id: Optional[str] = None

    def __post_init__(self) -> None:
        required_text = {
            "trigger_id": self.trigger_id,
            "source_ref": self.source_ref,
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
            "correlation_id": self.correlation_id,
            "received_at": self.received_at,
        }
        for field_name, value in required_text.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")

        if self.project_id is not None and (
            not isinstance(self.project_id, str) or not self.project_id.strip()
        ):
            raise ValueError("project_id must be null or a non-empty string")
        if self.claim_generation is not None and (
            type(self.claim_generation) is not int or self.claim_generation < 1
        ):
            raise ValueError("claim_generation must be at least 1 when present")

        if self.source_type == "PROMPT":
            if self.agent_type != "IA":
                raise ValueError("PROMPT requires agent_type=IA")
            return

        if self.source_type != "CLAIMED_WORKITEM":
            raise ValueError("unsupported source_type")
        if self.agent_type not in {"CA", "PA", "EA"}:
            raise ValueError("CLAIMED_WORKITEM requires agent_type=CA|PA|EA")

        claimed_required = {
            "project_id": self.project_id,
            "work_item_ref": self.work_item_ref,
            "claim_ref": self.claim_ref,
            "assignment_ref": self.assignment_ref,
        }
        for field_name, value in claimed_required.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"CLAIMED_WORKITEM requires non-empty {field_name}"
                )

class AgentExecutionTriggerSinkV21(Protocol):
    async def start_execution(self, trigger: ExecutionTriggerV21) -> str:
        """Idempotently create/return AgentExecution for a valid trigger."""
        ...
