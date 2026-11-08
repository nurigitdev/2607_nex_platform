from __future__ import annotations

from pathlib import Path

from nex_mo.provider_catalog import build_model_profile_catalog
from nex_mo.remote_provider import build_remote_generation_execution_config
from nex_runtime.canonical_generation_binding import CANONICAL_GENERATION_BINDING


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_generation_binding_owns_active_defaults() -> None:
    binding = CANONICAL_GENERATION_BINDING
    assert binding.model_name == "Qwen3.5-9B"
    assert binding.model_revision == "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    assert binding.deployment_id == "dgx-qwen3-5-9b-9111"
    assert binding.provider_port == 9111
    assert binding.precision == "BF16"
    assert binding.reasoning_mode == "disabled"

    selected = next(
        profile
        for profile in build_model_profile_catalog({})
        if profile.provider_capability == "generation" and profile.selected
    )
    rollback = next(
        profile
        for profile in build_model_profile_catalog({})
        if profile.profile_name == "qwen3_5_4b_bf16"
    )
    assert selected.model_name == binding.model_name
    assert selected.profile_name == binding.profile_name
    assert rollback.selected is False
    assert rollback.candidate_role == "rollback"

    execution = build_remote_generation_execution_config({})
    assert execution.model_name == binding.model_name
    assert execution.model_revision == binding.model_revision
    assert execution.deployment_id == binding.deployment_id


def test_canonical_generation_binding_matches_deployment_defaults() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (
        ROOT / "deployment/compose/canonical-platform.override.yaml"
    ).read_text(encoding="utf-8")
    route = (
        ROOT / "deployment/compose/traefik/canonical-platform-dynamic.yaml"
    ).read_text(encoding="utf-8")
    binding = CANONICAL_GENERATION_BINDING

    for source in (env_example, compose):
        assert f"NEX_MO_VLLM_MODEL={binding.model_name}" in source or (
            f"NEX_MO_VLLM_MODEL:-{binding.model_name}" in source
        )
        assert binding.model_revision in source
        assert binding.deployment_id in source
    assert f"192.168.20.243:{binding.provider_port}" in route
