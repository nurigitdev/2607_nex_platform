from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nex_mo.provider_projection import project_model_profile


DEFAULT_MODEL_ROOT = "/data/nex-platform/models"
DEFAULT_PROVIDER_MODE = "mock"
DEFAULT_GENERATION_PROFILE = "qwen3_5_4b_bf16"
GENERATION_PROFILE_CANDIDATES: tuple[dict[str, str], ...] = (
    {
        "profile_name": "qwen3_5_4b_bf16",
        "alias": "general-llm-default",
        "model_name": "Qwen3.5-4B",
        "model_path_suffix": "qwen3.5-4b-bf16",
        "precision": "BF16",
        "candidate_role": "primary",
        "selection_reason": "Current DGX-Spark vLLM generation target.",
    },
    {
        "profile_name": "qwen3_6_27b_nvfp4",
        "alias": "general-llm-fast",
        "model_name": "Qwen3.6-27B-NVFP4",
        "model_path_suffix": "qwen3.6-27b-nvfp4",
        "precision": "NVFP4",
        "candidate_role": "candidate",
        "selection_reason": "Lower-latency generation candidate.",
    },
    {
        "profile_name": "k_ai_generation_candidate",
        "alias": "general-llm-kai-candidate",
        "model_name": "K-AI generation model",
        "model_path_suffix": "k-ai-generation-candidate",
        "precision": "NVFP4",
        "candidate_role": "planned",
        "selection_reason": "Domestic K-AI generation model planned for evaluation.",
    },
)


@dataclass(frozen=True)
class ModelProfile:
    profile_name: str
    provider_capability: str
    alias: str
    provider_mode: str
    model_name: str
    precision: str
    runtime_engine: str
    model_path: str
    selected: bool
    status: str
    candidate_role: str = "primary"
    selection_reason: str = ""
    live_health_env: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return project_model_profile(self)


def build_model_profile_catalog(
    environ: dict[str, str] | None = None,
) -> tuple[ModelProfile, ...]:
    env = environ if environ is not None else os.environ
    provider_mode = env.get("NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE)
    model_root = Path(env.get("NEX_MO_MODEL_ROOT", DEFAULT_MODEL_ROOT))
    status = "READY" if provider_mode == "mock" else "CONFIGURED"
    live_runtime_engine = "local_mock" if provider_mode == "mock" else "remote_http"
    selected_generation_profile = env.get(
        "NEX_MO_GENERATION_PROFILE",
        DEFAULT_GENERATION_PROFILE,
    )

    profiles: list[ModelProfile] = [
        ModelProfile(
            profile_name=env.get("NEX_MO_EMBEDDING_PROFILE", "qwen3_embedding_4b_bf16"),
            provider_capability="embedding",
            alias="mock-embedding-default",
            provider_mode=provider_mode,
            model_name="Qwen3-Embedding-4B",
            precision="BF16",
            runtime_engine=live_runtime_engine,
            model_path=env.get(
                "NEX_MO_EMBEDDING_MODEL_PATH",
                str(model_root / "qwen3-embedding-4b-bf16"),
            ),
            selected=True,
            status=status,
            candidate_role="primary",
            selection_reason="Current default embedding model from NeX-PCX.",
            live_health_env="NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
        ),
        ModelProfile(
            profile_name=env.get("NEX_MO_RERANKER_PROFILE", "qwen3_reranker_4b_bf16"),
            provider_capability="reranking",
            alias="mock-reranker-default",
            provider_mode=provider_mode,
            model_name="Qwen3-Reranker-4B",
            precision="BF16",
            runtime_engine=live_runtime_engine,
            model_path=env.get(
                "NEX_MO_RERANKER_MODEL_PATH",
                str(model_root / "qwen3-reranker-4b-bf16"),
            ),
            selected=True,
            status=status,
            candidate_role="primary",
            selection_reason="Current DGX-Spark remote reranker target.",
            live_health_env="NEX_MO_LIVE_RERANKER_HEALTH_URL",
        ),
    ]
    profiles.extend(
        build_generation_model_profiles(
            env=env,
            model_root=model_root,
            provider_mode=provider_mode,
            selected_generation_profile=selected_generation_profile,
        )
    )
    return tuple(profiles)


def build_generation_model_profiles(
    *,
    env: dict[str, str],
    model_root: Path,
    provider_mode: str,
    selected_generation_profile: str,
) -> tuple[ModelProfile, ...]:
    profiles: list[ModelProfile] = []
    selected_known_profile = selected_generation_profile in {
        candidate["profile_name"] for candidate in GENERATION_PROFILE_CANDIDATES
    }
    selected_profile_name = selected_generation_profile if selected_known_profile else ""
    for candidate in GENERATION_PROFILE_CANDIDATES:
        profile_name = candidate["profile_name"]
        selected = profile_name == selected_profile_name
        planned = candidate["candidate_role"] == "planned"
        profiles.append(
            ModelProfile(
                profile_name=profile_name,
                provider_capability="generation",
                alias=candidate["alias"],
                provider_mode=provider_mode,
                model_name=candidate["model_name"],
                precision=candidate["precision"],
                runtime_engine="vllm",
                model_path=generation_model_path(
                    env,
                    model_root,
                    profile_name=profile_name,
                    default_suffix=candidate["model_path_suffix"],
                    selected=selected,
                ),
                selected=selected,
                status=model_profile_status(
                    provider_mode=provider_mode,
                    selected=selected,
                    planned=planned,
                ),
                candidate_role=candidate["candidate_role"],
                selection_reason=candidate["selection_reason"],
                live_health_env="NEX_MO_LIVE_VLLM_MODELS_URL",
            )
        )
    if not selected_known_profile:
        profiles.append(
            ModelProfile(
                profile_name=selected_generation_profile,
                provider_capability="generation",
                alias="general-llm-custom",
                provider_mode=provider_mode,
                model_name=env.get(
                    "NEX_MO_GENERATION_MODEL_NAME", selected_generation_profile
                ),
                precision="NVFP4",
                runtime_engine="vllm",
                model_path=env.get(
                    "NEX_MO_GENERATION_MODEL_PATH",
                    str(model_root / selected_generation_profile),
                ),
                selected=True,
                status=model_profile_status(
                    provider_mode=provider_mode,
                    selected=True,
                    planned=False,
                ),
                candidate_role="custom",
                selection_reason="Operator-selected generation profile override.",
                live_health_env="NEX_MO_LIVE_VLLM_MODELS_URL",
            )
        )
    return tuple(profiles)


def generation_model_path(
    env: dict[str, str],
    model_root: Path,
    *,
    profile_name: str,
    default_suffix: str,
    selected: bool,
) -> str:
    profile_specific_env = {
        "qwen3_5_4b_bf16": "NEX_MO_GENERATION_QWEN35_4B_MODEL_PATH",
        "qwen3_6_27b_nvfp4": "NEX_MO_GENERATION_QWEN36_27B_MODEL_PATH",
        "k_ai_generation_candidate": "NEX_MO_GENERATION_KAI_MODEL_PATH",
    }[profile_name]
    if profile_specific_env in env:
        return env[profile_specific_env]
    if selected and "NEX_MO_GENERATION_MODEL_PATH" in env:
        return env["NEX_MO_GENERATION_MODEL_PATH"]
    return str(model_root / default_suffix)


def model_profile_status(*, provider_mode: str, selected: bool, planned: bool) -> str:
    if planned:
        return "PLANNED"
    if provider_mode == "mock" and selected:
        return "READY"
    return "CONFIGURED"


def list_model_profiles(
    capability: str | None = None,
    profiles: tuple[ModelProfile, ...] | None = None,
) -> list[ModelProfile]:
    selected_profiles = profiles or build_model_profile_catalog()
    if capability is None:
        return list(selected_profiles)
    return [
        profile
        for profile in selected_profiles
        if profile.provider_capability == capability
    ]
