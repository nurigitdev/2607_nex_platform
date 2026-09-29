from __future__ import annotations

import json

import pytest

import nex_mo.provider_readiness_plan as readiness_plan
from nex_mo.provider_readiness_plan import (
    ProviderReadinessPlanError,
    build_provider_readiness_probe_plan,
)
from nex_mo.provider_registry import DEFAULT_PROVIDER_ROUTES
import run_mo_provider_readiness_plan as runner


def live_env() -> dict[str, str]:
    return {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://private.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_RERANKER_URL": "http://private.local:9113/v1/rerank",
        "NEX_MO_VLLM_BASE_URL": "http://private.local:9111",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        "NEX_MO_VLLM_API_KEY": "generation-secret",
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "dgx-embedding",
        "NEX_MO_REMOTE_RERANKER_DEPLOYMENT_ID": "dgx-reranker",
        "NEX_MO_VLLM_DEPLOYMENT_ID": "dgx-generation",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "Qwen3-Embedding-4B",
        "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": "Qwen3-Reranker-4B",
        "NEX_MO_VLLM_MODEL_REVISION": "Qwen3.5-4B",
    }


def test_mock_probe_plan_is_deterministic_and_network_free() -> None:
    plan = build_provider_readiness_probe_plan({})

    assert plan.provider_mode == "mock"
    assert [target.provider_capability for target in plan.targets] == [
        "embedding",
        "reranking",
        "generation",
    ]
    assert all(target.method == "LOCAL" for target in plan.targets)
    assert all(target.request_shape == "deterministic_mock" for target in plan.targets)
    assert all(target.timeout_seconds == 0 for target in plan.targets)
    assert all(target.preflight_config is None for target in plan.targets)
    assert all(target.route_status == "READY" for target in plan.targets)
    assert plan.target_for("generation").alias == "general-llm-default"


def test_live_probe_plan_reuses_preflight_and_execution_identity() -> None:
    plan = build_provider_readiness_probe_plan(live_env())
    embedding = plan.target_for("embedding")
    reranking = plan.target_for("reranking")
    generation = plan.target_for("generation")

    assert embedding.request_shape == "openai_embeddings"
    assert reranking.request_shape == "rerank"
    assert generation.request_shape == "openai_models"
    assert [target.method for target in plan.targets] == ["POST", "POST", "GET"]
    assert [target.deployment_id for target in plan.targets] == [
        "dgx-embedding",
        "dgx-reranker",
        "dgx-generation",
    ]
    assert [target.model_revision for target in plan.targets] == [
        "Qwen3-Embedding-4B",
        "Qwen3-Reranker-4B",
        "Qwen3.5-4B",
    ]
    assert all(target.configured for target in plan.targets)
    assert all(target.authorization_configured for target in plan.targets)
    assert all(target.preflight_config is not None for target in plan.targets)


def test_safe_summary_omits_endpoints_credentials_and_private_config() -> None:
    plan = build_provider_readiness_probe_plan(live_env())
    serialized = json.dumps(plan.to_safe_summary(), sort_keys=True)

    assert plan.to_safe_summary()["probe_plan_schema_version"] == (
        "mo_provider_readiness_probe_plan.v1"
    )
    assert "private.local" not in serialized
    assert "secret" not in serialized
    assert "preflight_config" not in serialized
    assert '"url"' not in serialized
    assert '"api_key"' not in serialized


def test_live_plan_retains_unconfigured_targets_for_fail_closed_evaluation() -> None:
    plan = build_provider_readiness_probe_plan({"NEX_MO_PROVIDER_MODE": "live"})

    assert len(plan.targets) == 3
    assert not any(target.configured for target in plan.targets)
    assert plan.target_for("generation").expected_models == ("Qwen3.5-4B",)


@pytest.mark.parametrize(
    ("environ", "failure_code"),
    [
        ({"NEX_MO_PROVIDER_MODE": "invalid"}, "provider_mode_invalid"),
    ],
)
def test_probe_plan_rejects_invalid_mode(
    environ: dict[str, str],
    failure_code: str,
) -> None:
    with pytest.raises(ProviderReadinessPlanError) as exc_info:
        build_provider_readiness_probe_plan(environ)

    assert str(exc_info.value) == failure_code


def test_probe_plan_rejects_invalid_missing_and_duplicate_routes() -> None:
    with pytest.raises(ProviderReadinessPlanError, match="required_capabilities_invalid"):
        build_provider_readiness_probe_plan({}, required_capabilities=())
    with pytest.raises(ProviderReadinessPlanError, match="required_capabilities_invalid"):
        build_provider_readiness_probe_plan(
            {}, required_capabilities=("embedding", "embedding")
        )
    with pytest.raises(ProviderReadinessPlanError, match="provider_route_missing"):
        build_provider_readiness_probe_plan({}, routes=DEFAULT_PROVIDER_ROUTES[1:])
    with pytest.raises(ProviderReadinessPlanError, match="provider_route_not_unique"):
        build_provider_readiness_probe_plan(
            {}, routes=(*DEFAULT_PROVIDER_ROUTES, DEFAULT_PROVIDER_ROUTES[0])
        )


def test_target_for_fails_closed_when_target_is_missing_or_duplicated() -> None:
    plan = build_provider_readiness_probe_plan({})
    with pytest.raises(ProviderReadinessPlanError, match="probe_target_not_unique"):
        plan.target_for("unknown")

    duplicated = plan.__class__(
        provider_mode=plan.provider_mode,
        required_capabilities=plan.required_capabilities,
        targets=(*plan.targets, plan.targets[0]),
    )
    with pytest.raises(ProviderReadinessPlanError, match="probe_target_not_unique"):
        duplicated.target_for("embedding")


def test_required_config_fails_closed_when_capability_is_missing() -> None:
    with pytest.raises(ProviderReadinessPlanError, match="provider_config_missing"):
        readiness_plan._required_config({}, "embedding")


def test_plan_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_readiness_plan()
    assert "readiness_plan=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_provider_readiness_plan", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "live=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_readiness_plan",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
