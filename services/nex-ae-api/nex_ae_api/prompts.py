from __future__ import annotations

from nex_runtime.prompts import PromptRegistryStore, PromptSeed, seed_prompt_registry


AE_GROUNDED_CHAT_BINDING = "ae.grounded_chat.default"
AE_GENERAL_ANSWER_BINDING = "ae.general_answer.default"
AE_DOCUMENT_SUMMARY_BINDING = "ae.document_summary.default"
AE_DOCUMENT_GENERATION_BINDING = "ae.document_generation.default"

DEFAULT_AE_PROMPT_STORE = PromptRegistryStore()

AE_PROMPT_SEEDS = [
    PromptSeed(
        service_id="nex-ae-api",
        purpose="general_answer",
        name="default_general_answer_system",
        owner_domain="agent-experience",
        binding_key=AE_GENERAL_ANSWER_BINDING,
        version="v1",
        role="system",
        segment_order=0,
        content=(
            "Answer the user request directly. Do not invent source citations. "
            "State uncertainty when required context is unavailable."
        ),
        model_capability="generation",
        metadata={"slice": "1024", "retrieval_required": False},
    ),
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
    ),
    PromptSeed(
        service_id="nex-ae-api",
        purpose="document_summary",
        name="default_document_summary_system",
        owner_domain="agent-experience",
        binding_key=AE_DOCUMENT_SUMMARY_BINDING,
        version="v1",
        role="system",
        segment_order=0,
        content=(
            "Produce a source-traceable document summary using only supplied CX "
            "evidence and preserve material dates and decisions."
        ),
        model_capability="generation",
        metadata={"slice": "1024", "retrieval_required": True},
    ),
    PromptSeed(
        service_id="nex-ae-api",
        purpose="document_generation",
        name="default_document_generation_system",
        owner_domain="agent-experience",
        binding_key=AE_DOCUMENT_GENERATION_BINDING,
        version="v1",
        role="system",
        segment_order=0,
        content=(
            "Create the requested structured document from supplied CX evidence. "
            "Follow the resolved template, output, and citation policies."
        ),
        model_capability="generation",
        metadata={"slice": "1024", "retrieval_required": True},
    ),
]


def seed_ae_prompt_registry(
    store: PromptRegistryStore = DEFAULT_AE_PROMPT_STORE,
) -> list[dict[str, object]]:
    return seed_prompt_registry(store, AE_PROMPT_SEEDS)


seed_ae_prompt_registry()
