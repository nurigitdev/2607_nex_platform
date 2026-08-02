from __future__ import annotations

from nex_runtime.prompts import PromptRegistryStore, PromptSeed, seed_prompt_registry


AE_GROUNDED_CHAT_BINDING = "ae.grounded_chat.default"

DEFAULT_AE_PROMPT_STORE = PromptRegistryStore()

AE_PROMPT_SEEDS = [
    PromptSeed(
        service_id="nex-ae-api",
        purpose="grounded_chat",
        name="default_grounded_chat_system",
        owner_domain="agent-experience",
        binding_key=AE_GROUNDED_CHAT_BINDING,
        version="v1",
        role="system",
        segment_order=0,
        content=(
            "Answer using only supplied CX evidence. When evidence is insufficient, "
            "say that the answer cannot be grounded. Keep citations traceable."
        ),
        model_capability="generation",
        metadata={"slice": "0029", "retrieval_required": True},
    )
]


def seed_ae_prompt_registry(
    store: PromptRegistryStore = DEFAULT_AE_PROMPT_STORE,
) -> list[dict[str, object]]:
    return seed_prompt_registry(store, AE_PROMPT_SEEDS)


seed_ae_prompt_registry()
