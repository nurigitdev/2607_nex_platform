from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalGenerationBinding:
    profile_name: str
    alias: str
    model_name: str
    model_revision: str
    deployment_id: str
    provider_port: int
    precision: str
    reasoning_mode: str


CANONICAL_GENERATION_BINDING = CanonicalGenerationBinding(
    profile_name="qwen3_8_flash_next_fp4",
    alias="general-llm-default",
    model_name="Qwen3.8-Flash-Next",
    model_revision="hf:fc694b54fb0174e0913e6adf86691ef85a4ead47",
    deployment_id="dgx-qwen3-8-flash-next-9111",
    provider_port=9111,
    precision="BF16",
    reasoning_mode="disabled",
)
