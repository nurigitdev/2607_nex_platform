from __future__ import annotations
from typing import Protocol, Mapping, Any, Optional

Json = Mapping[str, Any]

class AgentRegistryV21(Protocol):
    async def create(self, identity: Json) -> Json:
        """Atomically create AgentIdentity.
        PA invariant: at most one ACTIVE PA per (tenant_id, project_id).
        Conflict must be returned as a deterministic domain error, e.g. ACTIVE_PA_ALREADY_EXISTS.
        """
        ...

    async def get(self, *, tenant_id: str, agent_id: str) -> Json | None: ...

    async def get_active_project_agent(self, *, tenant_id: str, project_id: str) -> Json | None: ...

    async def transition_status(
        self, *, tenant_id: str, agent_id: str, expected_version: int, new_status: str
    ) -> Json: ...
