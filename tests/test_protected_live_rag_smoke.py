from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import run_protected_live_rag_smoke as smoke


def live_env() -> dict[str, str]:
    return {
        "NEX_PROTECTED_LIVE_RAG_SMOKE": "1",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "live-embedding-secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.local:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "live-reranker-secret",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": "http://dgx.local:12000/v1/chat/completions",
        "NEX_MO_VLLM_API_KEY": "live-generation-secret",
    }


def test_protected_live_rag_smoke_skips_by_default() -> None:
    evidence = smoke.run_protected_live_rag_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["activation"]["enabled"] is False
    assert evidence["issues"][0]["error_code"] == "protected_live_rag_smoke_not_enabled"


def test_protected_live_rag_smoke_reports_configuration_issues() -> None:
    evidence = smoke.run_protected_live_rag_smoke(
        {
            "NEX_PROTECTED_LIVE_RAG_SMOKE": "1",
            "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "nex_pcx_embeddings_v1",
            "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "nex_pcx_rerank_v1",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["stage_status"]["configuration"] == "FAIL"
    assert {
        issue["error_code"] for issue in evidence["issues"]
    } >= {
        "provider_endpoint_missing",
        "embedding_request_shape_not_compatible",
        "reranker_request_shape_not_compatible",
    }


def test_protected_live_rag_smoke_runs_live_shape_and_redacts_values() -> None:
    calls: list[dict[str, object]] = []

    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        payload = kwargs["json"]
        if url.endswith("/v1/embeddings"):
            inputs = payload["input"]
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "object": "embedding",
                            "index": index,
                            "embedding": [0.1, 0.2, 0.3, 0.4],
                        }
                        for index, _ in enumerate(inputs)
                    ],
                    "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
                },
            )
        if url.endswith("/v1/rerank"):
            assert payload["model"] == "Qwen3-Reranker-0.6B"
            return httpx.Response(
                200,
                json={
                    "results": [{"index": 0, "relevance_score": 0.93}],
                    "usage": {"prompt_tokens": 4, "total_tokens": 4},
                },
            )
        assert payload["model"] == "Qwen3.5-122B-A10B-NVFP4"
        assert payload["messages"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-live-rag-smoke",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Protected live RAG smoke answer.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 5,
                    "total_tokens": 16,
                },
            },
        )

    evidence = smoke.run_protected_live_rag_smoke(
        live_env(),
        requester=requester,
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert evidence["stage_status"]["rag_flow"] == "PASS"
    assert evidence["rag_evidence"]["retrieval"]["status"] == "READY"
    assert evidence["rag_evidence"]["retrieval"]["rerank_state"] == "APPLIED"
    assert evidence["rag_evidence"]["generation"]["status"] == "COMPLETED"
    assert evidence["rag_evidence"]["generation"]["mo_generation_id"] == (
        "chatcmpl-live-rag-smoke"
    )
    assert all(evidence["rag_evidence"]["assertions"].values())
    assert [call["url"] for call in calls] == [
        "http://dgx.local:9112/v1/embeddings",
        "http://dgx.local:9113/v1/rerank",
        "http://dgx.local:12000/v1/chat/completions",
    ]
    assert calls[0]["headers"]["Authorization"] == "Bearer live-embedding-secret"
    assert calls[1]["headers"]["Authorization"] == "Bearer live-reranker-secret"
    assert calls[2]["headers"]["Authorization"] == "Bearer live-generation-secret"
    assert "http://dgx.local" not in serialized
    assert "live-embedding-secret" not in serialized
    assert "live-reranker-secret" not in serialized
    assert "live-generation-secret" not in serialized
    assert smoke.SMOKE_TEXT not in serialized


def test_protected_live_rag_smoke_reports_safe_flow_failure() -> None:
    def requester(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(500, json={"error": "failed"})

    evidence = smoke.run_protected_live_rag_smoke(
        live_env(),
        requester=requester,
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "FAIL"
    assert evidence["stage_status"]["rag_flow"] == "FAIL"
    assert evidence["issues"][0]["detail"] == "Protected live RAG smoke flow failed."
    assert "http://dgx.local" not in serialized
    assert "live-embedding-secret" not in serialized


def test_assert_live_rag_evidence_reports_mismatch() -> None:
    evidence = minimal_assertion_inputs()
    evidence["retrieval"]["status"] = "LOW_CONFIDENCE"

    with pytest.raises(AssertionError):
        smoke.assert_live_rag_evidence(**evidence)


def test_summary_line_handles_fail_and_pass() -> None:
    failure = {
        "status": "FAIL",
        "stage_status": {"configuration": "FAIL", "rag_flow": "PASS"},
    }
    success = {
        "status": "PASS",
        "rag_evidence": {
            "retrieval": {"status": "READY", "rerank_state": "APPLIED"},
            "generation": {"status": "COMPLETED"},
        },
    }

    assert smoke.summary_line(failure) == (
        "protected_live_rag_smoke=fail failed_stages=configuration"
    )
    assert smoke.summary_line(success) == (
        "protected_live_rag_smoke=pass retrieval=READY "
        "rerank=APPLIED generation=COMPLETED"
    )


def test_patched_remote_request_accepts_noop_requester() -> None:
    original_request = smoke.remote_provider.httpx.request

    with smoke.patched_remote_request(None):
        assert smoke.remote_provider.httpx.request is original_request

    assert smoke.remote_provider.httpx.request is original_request


def test_safe_response_json_handles_non_json_and_non_object() -> None:
    assert smoke._safe_response_json(httpx.Response(200, content=b"not-json")) == {}
    assert smoke._safe_response_json(httpx.Response(200, json=["not", "object"])) == {}


def test_in_process_live_mo_client_maps_rerank_problem() -> None:
    app = FastAPI()

    @app.post("/api/v1/rerank")
    def fail_rerank():
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "mo.remote_reranker_throttled",
                "detail": "Reranker throttled.",
                "retryable": True,
            },
        )

    client = smoke.InProcessLiveMoClient(TestClient(app))

    with pytest.raises(smoke.RetrievalError) as exc_info:
        client.rerank_documents(
            "query",
            ["document"],
            alias="mock-reranker-default",
            top_n=1,
            request_id=smoke.REQUEST_ID,
            trace_id=smoke.TRACE_ID,
        )

    assert exc_info.value.error_code == "mo.remote_reranker_throttled"
    assert exc_info.value.retryable is True


def test_in_process_live_mo_client_maps_generation_problem() -> None:
    app = FastAPI()

    @app.post("/api/v1/generations")
    def fail_generation():
        return JSONResponse(
            status_code=503,
            content={
                "error_code": "mo.remote_generation_not_configured",
                "detail": "Generation provider missing.",
                "retryable": True,
            },
        )

    client = smoke.InProcessLiveMoClient(TestClient(app))

    with pytest.raises(smoke.GenerationFacadeError) as exc_info:
        client.create_generation(
            {"messages": [{"role": "user", "content": "hello"}]},
            request_id=smoke.REQUEST_ID,
            trace_id=smoke.TRACE_ID,
        )

    assert exc_info.value.error_code == "mo.remote_generation_not_configured"
    assert exc_info.value.retryable is True


def test_assert_protected_live_rag_evidence_redaction_guard() -> None:
    with pytest.raises(ValueError) as exc_info:
        smoke.assert_protected_live_rag_evidence_redacted(
            '{"url":"http://dgx.local:9112/v1/embeddings"}',
            {"NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.local:9112/v1/embeddings"},
        )

    assert "NEX_MO_REMOTE_EMBEDDING_URL" in str(exc_info.value)


def test_protected_live_rag_smoke_main_summary_and_output(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.delenv("NEX_PROTECTED_LIVE_RAG_SMOKE", raising=False)

    assert smoke.main(["--summary"]) == 0
    assert "protected_live_rag_smoke=skipped" in capsys.readouterr().out

    output = tmp_path / "live" / "rag-smoke.json"
    assert smoke.main(["--output", str(output)]) == 0
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["evidence_schema_version"] == "protected_live_rag_smoke_evidence.v1"


def minimal_assertion_inputs() -> dict[str, object]:
    trace_id = smoke.TRACE_ID
    document_id = "doc-1"
    retrieval_package_id = "retrieval-1"
    return {
        "trace_id": trace_id,
        "upload": {"trace_id": trace_id, "document_id": document_id},
        "extraction": {"trace_id": trace_id, "document_id": document_id},
        "chunk_set": {"trace_id": trace_id, "document_id": document_id},
        "lexical_index": {"trace_id": trace_id, "document_id": document_id},
        "embedding_index": {"trace_id": trace_id, "document_id": document_id},
        "retrieval": {
            "trace_id": trace_id,
            "status": "READY",
            "retrieval_package_id": retrieval_package_id,
            "score_summary": {"rerank_state": "APPLIED"},
        },
        "generation": {
            "trace_id": trace_id,
            "status": "COMPLETED",
            "request_metadata": {
                "retrieval_package_id": retrieval_package_id,
            },
        },
        "telemetry": {
            "data": [
                {"capability": "embedding", "success_count": 1},
                {"capability": "reranking", "success_count": 1},
                {"capability": "generation", "success_count": 1},
            ]
        },
    }
