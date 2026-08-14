from __future__ import annotations

import json

import httpx
import pytest

import run_protected_remote_provider_live_smoke as smoke


def live_env() -> dict[str, str]:
    return {
        "NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE": "1",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.local:12000",
        "NEX_MO_VLLM_API_KEY": "generation-secret",
    }


def test_protected_remote_provider_live_smoke_skips_by_default() -> None:
    evidence = smoke.run_protected_remote_provider_live_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["activation"]["enabled"] is False
    assert evidence["provider_evidence"] is None
    assert evidence["issues"][0]["error_code"] == (
        "protected_remote_provider_live_smoke_not_enabled"
    )


def test_protected_remote_provider_live_smoke_reports_config_issues_without_calls() -> None:
    called = False

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    evidence = smoke.run_protected_remote_provider_live_smoke(
        {
            "NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE": "1",
            "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "nex_pcx_embeddings_v1",
            "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "nex_pcx_rerank_v1",
        },
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert called is False
    assert evidence["stage_status"] == {
        "activation": "PASS",
        "configuration": "FAIL",
    }
    assert {
        issue["error_code"] for issue in evidence["issues"]
    } >= {
        "provider_endpoint_missing",
        "embedding_request_shape_not_compatible",
        "reranker_request_shape_not_compatible",
    }


def test_protected_remote_provider_live_smoke_executes_three_providers_and_redacts() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/v1/embeddings"):
            assert kwargs["json"] == {
                "model": "Qwen3-Embedding-4B",
                "input": smoke.EMBEDDING_INPUTS,
            }
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "Qwen3-Embedding-4B",
                    "data": [
                        {
                            "object": "embedding",
                            "index": index,
                            "embedding": [0.1, 0.2, 0.3, 0.4],
                        }
                        for index, _ in enumerate(smoke.EMBEDDING_INPUTS)
                    ],
                    "usage": {"prompt_tokens": 7, "total_tokens": 7},
                },
            )
        if url.endswith("/v1/rerank"):
            assert kwargs["json"] == {
                "model": "Qwen3-Reranker-0.6B",
                "query": smoke.RERANK_QUERY,
                "documents": smoke.RERANK_DOCUMENTS,
                "top_n": 2,
            }
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 0, "relevance_score": 0.88},
                        {"index": 1, "relevance_score": 0.21},
                    ],
                    "usage": {"prompt_tokens": 5, "total_tokens": 5},
                },
            )
        assert kwargs["json"]["model"] == "Qwen3.5-122B-A10B-NVFP4"
        assert kwargs["json"]["messages"] == [
            {"role": "user", "content": smoke.GENERATION_PROMPT}
        ]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-remote-live-smoke",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "remote provider live smoke ok",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 6,
                    "total_tokens": 17,
                },
            },
        )

    evidence = smoke.run_protected_remote_provider_live_smoke(
        live_env(),
        requester=requester,
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert evidence["stage_status"] == {
        "activation": "PASS",
        "configuration": "PASS",
        "embedding": "PASS",
        "reranking": "PASS",
        "generation": "PASS",
        "assertions": "PASS",
    }
    assert [call["url"] for call in calls] == [
        "http://dgx.local:9112/v1/embeddings",
        "http://dgx.local:9113/v1/rerank",
        "http://dgx.local:12000/v1/chat/completions",
    ]
    assert calls[0]["headers"]["Authorization"] == "Bearer embedding-secret"
    assert calls[1]["headers"]["Authorization"] == "Bearer reranker-secret"
    assert calls[2]["headers"]["Authorization"] == "Bearer generation-secret"
    assert evidence["provider_evidence"]["providers"]["embedding"]["observed"][
        "embedding_dimensions"
    ] == 4
    assert evidence["provider_evidence"]["providers"]["generation"]["observed"][
        "output_length"
    ] == len("remote provider live smoke ok")
    assert all(evidence["provider_evidence"]["assertions"].values())
    assert "dgx.local" not in serialized
    assert "embedding-secret" not in serialized
    assert "reranker-secret" not in serialized
    assert "generation-secret" not in serialized
    assert smoke.EMBEDDING_INPUTS[0] not in serialized
    assert smoke.RERANK_DOCUMENTS[0] not in serialized
    assert smoke.GENERATION_PROMPT not in serialized
    assert "remote provider live smoke ok" not in serialized


def test_protected_remote_provider_live_smoke_reports_safe_provider_failure() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    evidence = smoke.run_protected_remote_provider_live_smoke(
        live_env(),
        requester=requester,
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "FAIL"
    assert evidence["stage_status"]["embedding"] == "FAIL"
    assert evidence["issues"] == [
        {
            "stage": "embedding",
            "error_code": "mo.remote_embedding_http_error",
            "status_code": 503,
            "retryable": True,
            "degraded": True,
            "failure_kind": "upstream_5xx",
            "upstream_status_code": 503,
        }
    ]
    assert "dgx.local" not in serialized
    assert "embedding-secret" not in serialized


def test_protected_remote_provider_live_smoke_reports_assertion_failure(monkeypatch) -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/v1/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [0.1, 0.2]}
                        for index, _ in enumerate(smoke.EMBEDDING_INPUTS)
                    ],
                },
            )
        if url.endswith("/v1/rerank"):
            return httpx.Response(
                200,
                json={"results": [{"index": 0, "score": 0.8}]},
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-assertion-smoke",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        smoke,
        "assert_provider_evidence",
        lambda provider_evidence: (_ for _ in ()).throw(AssertionError("bad")),
    )

    evidence = smoke.run_protected_remote_provider_live_smoke(
        live_env(),
        requester=requester,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["stage_status"]["embedding"] == "PASS"
    assert evidence["stage_status"]["reranking"] == "PASS"
    assert evidence["stage_status"]["generation"] == "PASS"
    assert evidence["stage_status"]["assertions"] == "FAIL"
    assert evidence["issues"] == [
        {"stage": "assertions", "error_code": "AssertionError"}
    ]


def test_protected_remote_provider_live_smoke_summary_lines() -> None:
    assert smoke.summary_line(
        {"status": "SKIPPED", "stage_status": {"activation": "SKIPPED"}}
    ) == (
        "protected_remote_provider_live_smoke=skipped "
        "reason=NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE"
    )
    assert smoke.summary_line(
        {"status": "FAIL", "stage_status": {"configuration": "FAIL"}}
    ) == "protected_remote_provider_live_smoke=fail failed_stages=configuration"
    assert smoke.summary_line(
        {
            "status": "PASS",
            "provider_evidence": {
                "providers": {
                    "embedding": {"observed": {"embedding_dimensions": 4}},
                    "reranking": {"observed": {"top_index": 0}},
                    "generation": {"observed": {"finish_reason": "STOP"}},
                }
            },
        }
    ) == (
        "protected_remote_provider_live_smoke=pass "
        "embedding_dim=4 rerank_top=0 generation_finish=STOP"
    )


def test_protected_remote_provider_live_smoke_redaction_guard() -> None:
    with pytest.raises(ValueError) as exc_info:
        smoke.assert_evidence_redacted(
            '{"url":"http://dgx.local:9112/v1/embeddings"}',
            {"NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings"},
        )

    assert "NEX_MO_REMOTE_EMBEDDING_URL" in str(exc_info.value)

    with pytest.raises(ValueError) as raw_input:
        smoke.assert_evidence_redacted(
            json.dumps({"prompt": smoke.GENERATION_PROMPT}),
            {},
        )

    assert "generation_prompt" in str(raw_input.value)


def test_protected_remote_provider_live_smoke_main_summary_and_output(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    monkeypatch.delenv("NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE", raising=False)

    assert smoke.main(["--summary"]) == 0
    assert "protected_remote_provider_live_smoke=skipped" in capsys.readouterr().out

    output = tmp_path / "live" / "remote-provider-live-smoke.json"
    assert smoke.main(["--output", str(output)]) == 0
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["evidence_schema_version"] == (
        "protected_remote_provider_live_smoke_evidence.v1"
    )
    assert evidence["status"] == "SKIPPED"
