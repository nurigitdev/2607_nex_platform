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
    profile_name="qwen3_5_9b_bf16",
    alias="general-llm-default",
    model_name="Qwen3.5-9B",
    model_revision="hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a",
    deployment_id="dgx-qwen3-5-9b-9111",
    provider_port=9111,
    precision="BF16",
    reasoning_mode="disabled",
)
