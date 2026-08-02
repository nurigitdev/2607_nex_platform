from __future__ import annotations

from nex_runtime.prompts import PromptRegistryStore, PromptSeed, seed_prompt_registry


CX_DOCUMENT_SUMMARY_BINDING = "cx.document_summary.default"

DEFAULT_CX_PROMPT_STORE = PromptRegistryStore()

CX_PROMPT_SEEDS = [
    PromptSeed(
        service_id="nex-cx",
        purpose="document_summary",
        name="default_document_summary_system",
        owner_domain="content",
        binding_key=CX_DOCUMENT_SUMMARY_BINDING,
        version="v1",
        role="system",
        segment_order=0,
        content=(
            "Summarize extracted Markdown for retrieval. Keep the summary under "
            "{summary_max_chars} characters and never exceed {summary_hard_limit_chars} "
            "characters. Preserve concrete entities, dates, and user-visible decisions."
        ),
        model_capability="summary",
        summary_max_chars=900,
        summary_hard_limit_chars=1000,
        metadata={"slice": "0029", "policy": "summary_1000_0"},
    )
]


def seed_cx_prompt_registry(
    store: PromptRegistryStore = DEFAULT_CX_PROMPT_STORE,
) -> list[dict[str, object]]:
    return seed_prompt_registry(store, CX_PROMPT_SEEDS)


seed_cx_prompt_registry()
