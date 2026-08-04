from __future__ import annotations

import json

import pytest

import check_local_live_provider_config as live_config


def test_local_live_provider_config_skips_without_live_mode() -> None:
    snapshot = live_config.build_local_live_provider_config_snapshot({})

    assert snapshot["status"] == "SKIPPED"
    assert snapshot["provider_mode"] == "mock"
    assert snapshot["skip_reason"] == "NEX_MO_PROVIDER_MODE is not live."

    reranker_profile = next(
        profile
        for profile in snapshot["model_profiles"]
        if profile["provider_capability"] == "reranking"
    )
    assert reranker_profile["profile_name"] == "qwen3_reranker_0_6b_bf16"
    assert reranker_profile["model_name"] == "Qwen3-Reranker-0.6B"

    reranker_preflight = next(
        config
        for config in snapshot["preflight_configs"]
        if config["capability"] == "reranking"
    )
    assert reranker_preflight["expected_models"] == ["Qwen3-Reranker-0.6B"]
    assert "model_path" not in json.dumps(snapshot)
    assert "qwen3_4b_2560" not in json.dumps(snapshot)


def test_local_live_provider_config_passes_with_current_dgx_reranker_model() -> None:
    snapshot = live_config.build_local_live_provider_config_snapshot(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
            "NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000",
            "NEX_MO_VLLM_API_KEY": "secret-key",
        }
    )

    assert snapshot["status"] == "PASS"
    assert snapshot["issues"] == []
    assert snapshot["redaction"]["checked_env_keys"] == [
        "NEX_MO_REMOTE_EMBEDDING_URL",
        "NEX_MO_REMOTE_RERANKER_URL",
        "NEX_MO_VLLM_BASE_URL",
        "NEX_MO_VLLM_API_KEY",
    ]
    serialized = json.dumps(snapshot)
    assert "dgx.local" not in serialized
    assert "secret-key" not in serialized
    assert "qwen3_4b_2560" not in serialized

    reranker_config = next(
        config
        for config in snapshot["execution_configs"]
        if config["capability"] == "reranking"
    )
    assert reranker_config["model_name"] == "Qwen3-Reranker-0.6B"
    assert reranker_config["model_revision"] == "Qwen3-Reranker-0.6B"


def test_local_live_provider_config_reports_missing_endpoint_and_mismatch() -> None:
    snapshot = live_config.build_local_live_provider_config_snapshot(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9103/v1/embeddings",
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9104/v1/rerank",
            "NEX_MO_LIVE_EXPECTED_RERANKER_MODELS": "Qwen3-reranker-4B",
        }
    )

    assert snapshot["status"] == "FAIL"
    assert {issue["error_code"] for issue in snapshot["issues"]} == {
        "endpoint_not_configured",
        "expected_model_mismatch",
    }
    mismatch = next(
        issue
        for issue in snapshot["issues"]
        if issue["error_code"] == "expected_model_mismatch"
    )
    assert mismatch["capability"] == "reranking"
    assert mismatch["model_name"] == "Qwen3-Reranker-0.6B"
    assert mismatch["expected_models"] == ["Qwen3-reranker-4B"]


def test_local_live_provider_config_reports_invalid_timeout() -> None:
    snapshot = live_config.build_local_live_provider_config_snapshot(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_LIVE_TIMEOUT_SECONDS": "slow",
        }
    )

    assert snapshot["status"] == "FAIL"
    assert snapshot["issues"] == [
        {
            "capability": "all",
            "error_code": "live_timeout_invalid",
            "detail": "could not convert string to float: 'slow'",
        }
    ]


def test_local_live_provider_config_rejects_unredacted_env_values() -> None:
    with pytest.raises(ValueError) as exc_info:
        live_config.assert_config_snapshot_redacted(
            '{"url":"http://dgx.local:9104/v1/rerank"}',
            {
                "NEX_MO_REMOTE_RERANKER_URL": (
                    "http://dgx.local:9104/v1/rerank"
                ),
            },
        )

    assert "NEX_MO_REMOTE_RERANKER_URL" in str(exc_info.value)


def test_local_live_provider_config_main_summary_and_output(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.delenv("NEX_MO_PROVIDER_MODE", raising=False)

    assert live_config.main(["--summary"]) == 0
    assert "local_live_provider_config=skipped" in capsys.readouterr().out

    output = tmp_path / "live" / "local-live-provider-config.json"
    assert live_config.main(["--output", str(output)]) == 0
    snapshot = json.loads(output.read_text(encoding="utf-8"))
    assert snapshot["status"] == "SKIPPED"
    assert snapshot["config_schema_version"] == "local_live_provider_config_snapshot.v1"


def test_local_live_provider_config_main_returns_failure_for_live_missing_urls(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEX_MO_PROVIDER_MODE", "live")
    for key in live_config.PROTECTED_CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    assert live_config.main(["--summary"]) == 1
