from __future__ import annotations

import json

import httpx
import pytest

import run_protected_dgx_live_profile as protected_live


def live_env() -> dict[str, str]:
    return {
        protected_live.PROFILE_ENV: protected_live.DGX_PROFILE_NAME,
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "secret-key",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "secret-key",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000",
        "NEX_MO_VLLM_API_KEY": "secret-key",
    }


def test_protected_dgx_live_profile_skips_without_profile() -> None:
    evidence = protected_live.run_protected_dgx_live_profile({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["profile"]["enabled"] is False
    assert evidence["profile"]["resolved_profile"] is None
    assert evidence["stage_status"] == {
        "local_live_config": "NOT_RUN",
        "dgx_live_preflight": "NOT_RUN",
    }
    assert evidence["issues"][0]["error_code"] == "protected_profile_not_enabled"


def test_protected_dgx_live_profile_rejects_unknown_profile_without_network() -> None:
    called = False

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    evidence = protected_live.run_protected_dgx_live_profile(
        {protected_live.PROFILE_ENV: "staging"},
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert called is False
    assert evidence["issues"][0]["error_code"] == "protected_profile_unsupported"


def test_protected_dgx_live_profile_runs_config_guard_before_preflight() -> None:
    called = False

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    evidence = protected_live.run_protected_dgx_live_profile(
        {protected_live.PROFILE_ENV: protected_live.DGX_PROFILE_NAME},
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert called is False
    assert evidence["stage_status"] == {
        "local_live_config": "FAIL",
        "dgx_live_preflight": "NOT_RUN",
    }
    assert {issue["error_code"] for issue in evidence["issues"]} == {
        "endpoint_not_configured",
    }


def test_protected_dgx_live_profile_passes_and_redacts_live_values() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/v1/embeddings"):
            assert kwargs["json"] == {
                "model": "Qwen3-Embedding-4B",
                "input": ["nex live provider preflight"],
            }
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        if url.endswith("/v1/rerank"):
            assert kwargs["json"] == {
                "model": "Qwen3-Reranker-0.6B",
                "query": "nex live provider preflight",
                "documents": ["NeX live provider preflight document."],
                "top_n": 1,
            }
            return httpx.Response(
                200,
                json={"results": [{"index": 0, "relevance_score": 0.9}]},
            )
        return httpx.Response(
            200,
            json={"data": [{"id": "Qwen3.5-122B-A10B-NVFP4"}]},
        )

    evidence = protected_live.run_protected_dgx_live_profile(
        live_env(),
        requester=requester,
    )

    assert evidence["status"] == "PASS"
    assert evidence["profile"]["resolved_profile"] == protected_live.DGX_PROFILE_NAME
    assert evidence["profile"]["migration_policy"] == {
        "schema_version": protected_live.PROFILE_MIGRATION_SCHEMA_VERSION,
        "lane": "canonical_direct_vllm",
        "default_for_new_work": True,
        "legacy_pcx_shapes_allowed": False,
        "request_shapes": {
            "embedding": "openai_embeddings",
            "reranking": "rerank",
            "generation": "openai_chat_completions",
        },
        "legacy_profile": protected_live.DGX_PCX_LEGACY_PROFILE_NAME,
    }
    assert evidence["effective_flags"] == {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_LIVE_PREFLIGHT": "1",
    }
    assert evidence["stage_status"] == {
        "local_live_config": "PASS",
        "dgx_live_preflight": "PASS",
    }
    assert [call["method"] for call in calls] == ["POST", "POST", "GET"]
    assert evidence["config_snapshot"]["provider_mode"] == "live"
    assert evidence["config_snapshot"]["execution_configs"][0]["request_shape"] == (
        "openai_embeddings"
    )
    assert evidence["config_snapshot"]["execution_configs"][1]["request_shape"] == "rerank"
    assert evidence["preflight_evidence"]["status"] == "PASS"
    assert "NEX_MO_VLLM_API_KEY" in evidence["redaction"]["checked_env_keys"]

    serialized = json.dumps(evidence)
    assert "dgx.local" not in serialized
    assert "secret-key" not in serialized


def test_protected_dgx_live_profile_reports_live_preflight_failure() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/v1/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        if url.endswith("/v1/rerank"):
            return httpx.Response(
                200,
                json={"results": [{"index": 0, "relevance_score": 0.9}]},
            )
        return httpx.Response(200, json={"data": [{"id": "OtherGeneration"}]})

    evidence = protected_live.run_protected_dgx_live_profile(
        live_env(),
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["stage_status"] == {
        "local_live_config": "PASS",
        "dgx_live_preflight": "FAIL",
    }
    assert evidence["issues"] == [
        {
            "stage": "dgx_live_preflight",
            "error_code": "expected_model_missing",
            "capability": "generation",
        }
    ]


def test_protected_dgx_live_profile_uses_vllm_defaults() -> None:
    defaults = protected_live.protected_dgx_profile_defaults()

    assert defaults["NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE"] == (
        "openai_embeddings"
    )
    assert defaults["NEX_MO_REMOTE_EMBEDDING_MODEL"] == "Qwen3-Embedding-4B"
    assert defaults["NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE"] == "rerank"
    assert defaults["NEX_MO_REMOTE_RERANKER_MODEL"] == "Qwen3-Reranker-0.6B"


def test_protected_dgx_live_profile_keeps_legacy_pcx_defaults_separate() -> None:
    defaults = protected_live.protected_profile_defaults(
        protected_live.DGX_PCX_LEGACY_PROFILE_NAME,
    )
    policy = protected_live.profile_migration_policy(
        protected_live.DGX_PCX_LEGACY_PROFILE_NAME,
    )

    assert defaults["NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE"] == "nex_pcx_embeddings_v1"
    assert defaults["NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE"] == "nex_pcx_rerank_v1"
    assert defaults["NEX_MO_REMOTE_RERANKER_PROFILE_NAME"] == "qwen3_reranker_0_6b"
    assert policy["lane"] == "legacy_pcx_compatibility"
    assert policy["default_for_new_work"] is False
    assert policy["legacy_pcx_shapes_allowed"] is True
    assert protected_live.resolve_profile_name("dgx") == protected_live.DGX_PROFILE_NAME


def test_protected_dgx_live_profile_marks_disabled_migration_policy() -> None:
    policy = protected_live.profile_migration_policy(None)

    assert policy["lane"] == "disabled_or_unsupported"
    assert policy["canonical_profile"] == protected_live.DGX_PROFILE_NAME
    assert policy["legacy_profile"] == protected_live.DGX_PCX_LEGACY_PROFILE_NAME


def test_protected_dgx_live_profile_main_summary_and_output(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.delenv(protected_live.PROFILE_ENV, raising=False)

    assert protected_live.main(["--summary"]) == 0
    assert "protected_dgx_live_profile=skipped" in capsys.readouterr().out

    output = tmp_path / "live" / "protected-dgx-profile.json"
    assert protected_live.main(["--output", str(output)]) == 0
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "SKIPPED"
    assert evidence["profile_schema_version"] == "protected_dgx_live_profile.v1"


def test_protected_dgx_live_profile_main_fails_for_bad_profile(capsys) -> None:
    assert protected_live.main(["--profile", "bad", "--summary"]) == 1
    assert "protected_dgx_live_profile=fail" in capsys.readouterr().out


def test_protected_dgx_live_profile_rejects_unredacted_output() -> None:
    with pytest.raises(ValueError) as exc_info:
        protected_live.assert_profile_evidence_redacted(
            '{"url":"http://dgx.local:12000"}',
            {"NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000"},
        )

    assert "NEX_MO_VLLM_BASE_URL" in str(exc_info.value)
