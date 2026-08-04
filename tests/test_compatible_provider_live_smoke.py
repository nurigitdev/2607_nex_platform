from __future__ import annotations

import json

import httpx
import pytest

import run_compatible_provider_live_smoke as live_smoke


def live_env() -> dict[str, str]:
    return {
        "NEX_COMPAT_LIVE_SMOKE": "1",
        "NEX_COMPAT_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        "NEX_COMPAT_RERANKER_URL": "http://dgx.local:9113/v1/rerank",
        "NEX_COMPAT_EMBEDDING_API_KEY": "secret-embedding",
        "NEX_COMPAT_RERANKER_API_KEY": "secret-reranker",
        "NEX_COMPAT_LIVE_EXPECTED_EMBEDDING_DIMENSIONS": "4",
        "NEX_COMPAT_EMBEDDING_REQUEST_DIMENSIONS": "4",
    }


def models_response(model: str) -> dict[str, object]:
    return {"object": "list", "data": [{"id": model, "object": "model"}]}


def test_compatible_provider_live_smoke_skips_by_default() -> None:
    evidence = live_smoke.run_compatible_provider_live_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["runtime_engine"] == "vllm"
    assert evidence["checks"] == []
    assert evidence["skip_reason"] == "NEX_COMPAT_LIVE_SMOKE is not enabled."


def test_compatible_provider_live_smoke_passes_and_redacts_env_values() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        if url == "http://dgx.local:9112/v1/models":
            return httpx.Response(200, json=models_response("Qwen3-Embedding-4B"))
        if url == "http://dgx.local:9113/v1/models":
            return httpx.Response(200, json=models_response("Qwen3-Reranker-0.6B"))
        if url.endswith("/v1/embeddings"):
            assert kwargs["json"] == {
                "model": "Qwen3-Embedding-4B",
                "input": ["nex compatible provider live smoke"],
                "encoding_format": "float",
                "dimensions": 4,
            }
            return httpx.Response(
                200,
                json={
                    "id": "embd-test",
                    "object": "list",
                    "created": 1780000000,
                    "model": "Qwen3-Embedding-4B",
                    "data": [
                        {"object": "embedding", "embedding": [0.1, 0.2, 0.3, 0.4], "index": 0}
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 0,
                        "total_tokens": 5,
                        "prompt_tokens_details": {},
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "index": 0,
                        "relevance_score": 0.9,
                        "document": {"text": "NeX compatible provider live smoke document."},
                    }
                ],
            },
        )

    evidence = live_smoke.run_compatible_provider_live_smoke(
        live_env(),
        requester=requester,
    )
    protected = live_smoke.build_protected_smoke_evidence(evidence, live_env())

    assert evidence["status"] == "PASS"
    assert [check["status"] for check in evidence["checks"]] == [
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    assert [call["method"] for call in calls] == ["GET", "POST", "GET", "POST"]
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-embedding"
    assert calls[2]["headers"]["Authorization"] == "Bearer secret-reranker"
    assert evidence["bf16_evidence_policy"]["status"] == "OUT_OF_BAND"
    serialized = json.dumps(protected)
    assert "dgx.local" not in serialized
    assert "secret-embedding" not in serialized
    assert "secret-reranker" not in serialized


def test_compatible_provider_live_smoke_accepts_data_model_list_and_score_key() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        if url == "http://dgx.local:9112/v1/models":
            return httpx.Response(200, json={"models": ["Qwen3-Embedding-4B"]})
        if url == "http://dgx.local:9113/v1/models":
            return httpx.Response(200, json={"models": ["Qwen3-Reranker-0.6B"]})
        if url.endswith("/v1/embeddings"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "Qwen3-Embedding-4B",
                    "data": [{"object": "embedding", "embedding": [0.1] * 4, "index": 0}],
                    "usage": {"prompt_tokens": 5, "total_tokens": 5},
                },
            )
        return httpx.Response(
            200,
            json={
                "model": "Qwen3-Reranker-0.6B",
                "data": [{"index": 1, "score": 0.7}],
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            },
        )

    evidence = live_smoke.run_compatible_provider_live_smoke(
        live_env(),
        requester=requester,
    )

    assert evidence["status"] == "PASS"
    assert evidence["checks"][3]["observed"] == {
        "model": "Qwen3-Reranker-0.6B",
        "result_count": 1,
        "top_index": 1,
    }


def test_compatible_provider_live_smoke_reports_missing_model() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, json=models_response("OtherModel"))

    evidence = live_smoke.run_compatible_provider_live_smoke(
        live_env(),
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"][0]["failure_code"] == "expected_model_missing"


def test_compatible_provider_live_smoke_reports_response_dimension_mismatch() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        if url == "http://dgx.local:9112/v1/models":
            return httpx.Response(200, json=models_response("Qwen3-Embedding-4B"))
        if url == "http://dgx.local:9113/v1/models":
            return httpx.Response(200, json=models_response("Qwen3-Reranker-0.6B"))
        if url.endswith("/v1/embeddings"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "Qwen3-Embedding-4B",
                    "data": [{"object": "embedding", "embedding": [0.1], "index": 0}],
                    "usage": {"prompt_tokens": 5, "total_tokens": 5},
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [{"index": 0, "relevance_score": 0.9}],
            },
        )

    evidence = live_smoke.run_compatible_provider_live_smoke(
        live_env(),
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"][1]["failure_code"] == "embedding_dimension_mismatch"


def test_compatible_provider_live_smoke_reports_bad_rerank_shape() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/v1/models"):
            model = "Qwen3-Reranker-0.6B" if ":9113" in url else "Qwen3-Embedding-4B"
            return httpx.Response(200, json=models_response(model))
        if url.endswith("/v1/embeddings"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "Qwen3-Embedding-4B",
                    "data": [{"object": "embedding", "embedding": [0.1] * 4, "index": 0}],
                    "usage": {"prompt_tokens": 5, "total_tokens": 5},
                },
            )
        return httpx.Response(200, json={"results": [{"index": 0}]})

    evidence = live_smoke.run_compatible_provider_live_smoke(
        live_env(),
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"][3]["failure_code"] == "ValueError"


def test_compatible_provider_live_smoke_reports_missing_endpoint_and_bad_timeout() -> None:
    missing = live_smoke.run_compatible_provider_live_smoke(
        {
            "NEX_COMPAT_LIVE_SMOKE": "1",
            "NEX_COMPAT_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        },
        requester=lambda method, url, **kwargs: httpx.Response(200, json={}),
    )
    bad_timeout = live_smoke.run_compatible_provider_live_smoke(
        {"NEX_COMPAT_LIVE_SMOKE": "1", "NEX_COMPAT_LIVE_TIMEOUT_SECONDS": "slow"},
    )

    assert missing["status"] == "FAIL"
    assert missing["checks"][2]["failure_code"] == "models_url_not_configured"
    assert bad_timeout["status"] == "FAIL"
    assert bad_timeout["checks"][0]["failure_code"] == "configuration_invalid"


def test_compatible_provider_live_smoke_main_summary_and_output(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.delenv("NEX_COMPAT_LIVE_SMOKE", raising=False)

    assert live_smoke.main(["--summary"]) == 0
    assert "compatible_provider_live_smoke=skipped" in capsys.readouterr().out

    output = tmp_path / "live" / "compatible-provider-smoke.json"
    assert live_smoke.main(["--output", str(output)]) == 0
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["status"] == "SKIPPED"
    assert evidence["evidence_schema_version"] == (
        "compatible_provider_live_smoke_evidence.v1"
    )


def test_compatible_provider_live_smoke_redaction_guard() -> None:
    with pytest.raises(ValueError) as exc_info:
        live_smoke.assert_smoke_evidence_redacted(
            '{"url":"http://dgx.local:9112/v1/embeddings"}',
            {"NEX_COMPAT_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings"},
        )

    assert "NEX_COMPAT_EMBEDDING_URL" in str(exc_info.value)
