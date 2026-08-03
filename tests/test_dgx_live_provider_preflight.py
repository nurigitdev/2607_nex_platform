from __future__ import annotations

import json

import httpx
import pytest

import run_dgx_live_provider_preflight as dgx_preflight


def live_env() -> dict[str, str]:
    return {
        "NEX_MO_LIVE_PREFLIGHT": "1",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local/v1/embeddings",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local/v1/rerank",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000",
    }


def test_dgx_preflight_skips_when_not_enabled() -> None:
    evidence = dgx_preflight.run_dgx_live_provider_preflight({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["checks"] == []
    assert "qwen3_5_122b_a10b_nvfp4" in {
        profile["profile_name"] for profile in evidence["model_profiles"]
    }


def test_dgx_preflight_passes_when_expected_models_are_observed() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/v1/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        if url.endswith("/v1/rerank"):
            return httpx.Response(200, json={"results": [{"index": 0, "score": 0.91}]})
        return httpx.Response(
            200,
            json={"data": [{"id": "Qwen3.5-122B-A10B-NVFP4"}]},
        )

    evidence = dgx_preflight.run_dgx_live_provider_preflight(
        {
            **live_env(),
            "NEX_MO_LIVE_TIMEOUT_SECONDS": "7",
            "NEX_MO_VLLM_API_KEY": "secret-key",
        },
        requester=requester,
    )

    assert evidence["status"] == "PASS"
    assert [check["status"] for check in evidence["checks"]] == ["PASS", "PASS", "PASS"]
    assert [call["method"] for call in calls] == ["POST", "POST", "GET"]
    assert calls[0]["json"] == {
        "model": "Qwen3-embedding-4B",
        "input": ["nex live provider preflight"],
    }
    assert calls[1]["json"] == {
        "model": "Qwen3-reranker-4B",
        "query": "nex live provider preflight",
        "documents": ["NeX live provider preflight document."],
        "top_n": 1,
    }
    assert "json" not in calls[2]
    assert calls[2]["url"] == "http://dgx.local:12000/v1/models"
    assert calls[2]["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer secret-key",
    }
    assert [call["timeout"] for call in calls] == [7.0, 7.0, 7.0]
    assert "dgx.local" not in json.dumps(evidence)
    assert "secret-key" not in json.dumps(evidence)


def test_dgx_preflight_reports_missing_endpoint_and_model() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/v1/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
        if url.endswith("/v1/rerank"):
            return httpx.Response(200, json={"results": [{"relevance_score": 0.8}]})
        return httpx.Response(200, json={"data": [{"id": "OtherGeneration"}]})

    evidence = dgx_preflight.run_dgx_live_provider_preflight(
        {
            "NEX_MO_LIVE_PREFLIGHT": "1",
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local/v1/embeddings",
            "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local/v1/rerank",
            "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": "CustomGeneration",
        },
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"][2]["failure_code"] == "endpoint_not_configured"

    missing_model = dgx_preflight.run_dgx_live_provider_preflight(
        live_env(),
        requester=requester,
    )
    assert missing_model["status"] == "FAIL"
    assert missing_model["checks"][2]["failure_code"] == "expected_model_missing"
    assert missing_model["checks"][2]["missing_expected_models"] == [
        "Qwen3.5-122B-A10B-NVFP4",
    ]


def test_dgx_preflight_reports_fetch_errors_and_env_model_overrides() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("down")

    evidence = dgx_preflight.run_dgx_live_provider_preflight(
        {
            **live_env(),
            "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "EmbedA, EmbedB",
        },
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"][0]["expected_models"] == ["EmbedA", "EmbedB"]
    assert evidence["checks"][0]["failure_code"] == "ConnectError"


def test_dgx_preflight_main_summary_and_output(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.delenv("NEX_MO_LIVE_PREFLIGHT", raising=False)

    assert dgx_preflight.main(["--summary"]) == 0
    assert "dgx_live_provider_preflight=skipped" in capsys.readouterr().out

    output = tmp_path / "dgx-preflight.json"
    assert dgx_preflight.main(["--output", str(output)]) == 0
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "SKIPPED"


def test_dgx_preflight_main_returns_failure_when_enabled_without_urls(monkeypatch) -> None:
    monkeypatch.setenv("NEX_MO_LIVE_PREFLIGHT", "1")
    for check in dgx_preflight.LIVE_PROVIDER_CHECKS:
        monkeypatch.delenv(check.endpoint_env, raising=False)
        if check.legacy_endpoint_env:
            monkeypatch.delenv(check.legacy_endpoint_env, raising=False)
    monkeypatch.delenv("NEX_MO_VLLM_BASE_URL", raising=False)

    assert dgx_preflight.main(["--summary"]) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ("Default",)),
        ("", ("Default",)),
        ("A, B,,", ("A", "B")),
    ],
)
def test_expected_models_from_env(value: str | None, expected: tuple[str, ...]) -> None:
    assert dgx_preflight.expected_models_from_env(value, ("Default",)) == expected
