from __future__ import annotations

class EffectiveAuthorityBuilderV21:
    """Reference contract only. Agent identity is resolved by AE Agent Registry; OA owns authority evaluation."""
    async def build(self, *, tenant_id, principal, business_actor, agent_identity_ref, agent_type, role_binding_id, capability_id, work_item_id, auth_context, human_gate_state, correlation_id):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if agent_type not in {"IA","CA","PA","EA"}:
            raise ValueError("invalid agent_type")
        # Implementations MUST load current RoleBinding/Scope/Policy and MUST NOT infer tenant_id from org/project.
        # PA authority MUST be project bounded and MUST NOT union member permissions.
        ...
