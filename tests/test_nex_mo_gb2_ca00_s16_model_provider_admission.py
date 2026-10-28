from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from nex_mo.model_provider_admission import (
    MODEL_PROVIDER_ADMISSION_SCHEMA_VERSION,
    MODEL_PROVIDER_PROFILES,
    ModelProviderAdmissionError,
    _admit_target,
    _checked_at,
    admit_model_provider_readiness,
    resolve_model_provider_profile,
)
from nex_mo.provider_readiness_plan import build_provider_readiness_probe_plan

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)


def live_env() -> dict[str, str]:
    return {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_PROVIDER_DEPENDENCY_PROFILE": "rag",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://private.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-private-key",
        "NEX_MO_REMOTE_RERANKER_URL": "http://private.local:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-private-key",
        "NEX_MO_VLLM_BASE_URL": "http://private.local:9111",
        "NEX_MO_VLLM_API_KEY": "generation-private-key",
    }


def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
    if url.endswith("/v1/embeddings"):
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
    if url.endswith("/v1/rerank"):
        return httpx.Response(200, json={"results": [{"score": 0.9}]})
    return httpx.Response(200, json={"data": [{"id": "Qwen3.5-4B"}]})


def test_rag_profile_admits_three_live_providers_as_platform_dependencies() -> None:
    result = admit_model_provider_readiness(
        live_env(), requester=requester, now=lambda: NOW
    )
    serialized = json.dumps(result, sort_keys=True)

    assert result["schema_version"] == MODEL_PROVIDER_ADMISSION_SCHEMA_VERSION
    assert result["status"] == "PASS"
    assert result["admission_status"] == "ADMITTED"
    assert result["readiness_status"] == "READY"
    assert result["required_capabilities"] == [
        "embedding",
        "reranking",
        "generation",
    ]
    assert [item["dependency_id"] for item in result["dependency_readiness"]] == [
        "provider:embedding",
        "provider:reranking",
        "provider:generation",
    ]
    assert all(item["ready"] for item in result["dependency_readiness"])
    assert all(check["status"] == "PASS" for check in result["checks"])
    assert result["dependency_readiness_aggregate"]["readiness_status"] == "READY"
    assert "private.local" not in serialized
    assert "private-key" not in serialized
    assert "nex live provider preflight" not in serialized


def test_semantic_planning_requires_only_generation() -> None:
    calls: list[str] = []

    def generation_requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append(url)
        return httpx.Response(200, json={"data": [{"id": "Qwen3.5-4B"}]})

    result = admit_model_provider_readiness(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_PROVIDER_DEPENDENCY_PROFILE": "semantic_planning",
            "NEX_MO_VLLM_BASE_URL": "http://private.local:9111",
        },
        requester=generation_requester,
        now=lambda: NOW,
    )

    assert result["status"] == "PASS"
    assert result["required_capabilities"] == ["generation"]
    assert [item["capability"] for item in result["checks"]] == ["generation"]
    assert result["dependency_readiness_aggregate"][
        "missing_optional_dependency_ids"
    ] == ["provider:embedding", "provider:reranking"]
    assert len(calls) == 1 and calls[0].endswith("/v1/models")


def test_live_mode_without_successful_admission_fails_closed() -> None:
    result = admit_model_provider_readiness(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_PROVIDER_DEPENDENCY_PROFILE": "semantic_planning",
        },
        requester=lambda *args, **kwargs: pytest.fail("network must not run"),
        now=lambda: NOW,
    )

    assert result["status"] == "FAIL"
    assert result["admission_status"] == "BLOCKED"
    assert result["readiness_status"] == "NOT_READY"
    assert result["checks"][0]["configured"] is False
    assert result["dependency_readiness"][0]["ready"] is False


@pytest.mark.parametrize("timeout", ["5", "301"])
def test_timeout_policy_is_bounded_even_when_provider_responds(timeout: str) -> None:
    env = live_env()
    env["NEX_MO_VLLM_TIMEOUT_SECONDS"] = timeout

    result = admit_model_provider_readiness(
        env, requester=requester, now=lambda: NOW
    )

    generation = result["checks"][2]
    assert result["status"] == "FAIL"
    assert generation["bounded_request_succeeded"] is True
    assert generation["timeout_policy_valid"] is False
    assert result["dependency_readiness"][2]["provisioned"] is False


def test_provider_rejection_and_model_mismatch_are_bounded() -> None:
    def rejected(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(401, json={})

    rejected_result = admit_model_provider_readiness(
        live_env(), requester=rejected, now=lambda: NOW
    )
    assert rejected_result["status"] == "FAIL"
    assert all(check["authorized"] is False for check in rejected_result["checks"])
    assert all(check["failure_code"] == "http_status_401" for check in rejected_result["checks"])

    def mismatched(method: str, url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/v1/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        if url.endswith("/v1/rerank"):
            return httpx.Response(200, json={"results": [{"score": 0.9}]})
        return httpx.Response(200, json={"data": [{"id": "other-model"}]})

    mismatch = admit_model_provider_readiness(
        live_env(), requester=mismatched, now=lambda: NOW
    )
    assert mismatch["status"] == "FAIL"
    assert mismatch["checks"][2]["failure_code"] == "expected_model_missing"
    assert mismatch["checks"][2]["missing_expected_models"] == ["Qwen3.5-4B"]


def test_mock_mode_does_not_satisfy_live_admission() -> None:
    result = admit_model_provider_readiness({}, now=lambda: NOW)

    assert result["status"] == "FAIL"
    assert all(check["provider_mode_admitted"] is False for check in result["checks"])
    assert all(item["reachable"] is False for item in result["dependency_readiness"])

    accepted = admit_model_provider_readiness(
        {}, now=lambda: NOW, require_live=False
    )
    assert accepted["status"] == "PASS"
    assert all(check["timeout_policy_valid"] is True for check in accepted["checks"])


def test_profile_and_timestamp_validation_fail_closed() -> None:
    assert resolve_model_provider_profile({}) == (
        "rag",
        MODEL_PROVIDER_PROFILES["rag"],
    )
    with pytest.raises(ModelProviderAdmissionError, match="unsupported"):
        resolve_model_provider_profile(
            {"NEX_MO_PROVIDER_DEPENDENCY_PROFILE": "unknown"}
        )
    for value in (None, "bad", "2026-10-28T15:00:00"):
        with pytest.raises(ModelProviderAdmissionError, match="timestamp"):
            _checked_at(value)


def test_target_admission_rejects_identity_and_source_drift() -> None:
    plan = build_provider_readiness_probe_plan(
        {
            **live_env(),
            "NEX_MO_PROVIDER_DEPENDENCY_PROFILE": "semantic_planning",
        },
        required_capabilities=("generation",),
    )
    target = plan.targets[0]
    requirement = MODEL_PROVIDER_PROFILES["semantic_planning"][2]
    route = {
        "provider_capability": "generation",
        "alias": target.alias,
        "deployment_id": target.deployment_id,
        "model_revision": target.model_revision,
        "status": "READY",
        "source": "active_preflight",
    }

    identity_drift = _admit_target(
        requirement,
        target,
        {**route, "model_revision": "different"},
        provider_mode="live",
        require_live=True,
    )
    source_drift = _admit_target(
        requirement,
        replace(target, authorization_configured=False),
        {**route, "source": "mock_registry"},
        provider_mode="live",
        require_live=True,
    )

    assert identity_drift["model_identity_admitted"] is False
    assert identity_drift["status"] == "FAIL"
    assert source_drift["bounded_request_succeeded"] is False
    assert source_drift["authorization_configured"] is False
