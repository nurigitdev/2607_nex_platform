from dataclasses import dataclass
from typing import Protocol, Mapping, Any

@dataclass(frozen=True)
class CXAuthorityContext:
    tenant_id: str
    authority_ref: str
    authority_hash: str
    policy_version: str

class CXRetrievalClient(Protocol):
    def retrieve(self, tenant_id: str, query: str, authority_ref: str, **kwargs: Any) -> Mapping[str, Any]: ...
    def get_evidence_bundle(self, tenant_id: str, bundle_id: str, authority_ref: str) -> Mapping[str, Any]: ...
    def build_evidence_context(self, tenant_id: str, bundle_id: str, authority_ref: str) -> Mapping[str, Any]: ...

class AgentContextBuilderInput(Protocol):
    """Semantic boundary only: CX Evidence Context is an input, not AgentContext SoR."""
    def add_cx_evidence_context(self, context: Mapping[str, Any]) -> None: ...
