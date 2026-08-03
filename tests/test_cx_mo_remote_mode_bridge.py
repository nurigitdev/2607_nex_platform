from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import nex_mo.remote_provider as remote_provider
from nex_cx.chunking import register_chunking_routes
from nex_cx.embedding_index import (
    DEFAULT_EMBEDDING_ALIAS,
    EmbeddingIndexError,
    register_embedding_index_routes,
)
from nex_cx.generation import (
    GenerationExecutionStore,
    GenerationFacadeError,
    register_generation_routes,
)
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    register_ingestion_routes,
)
from nex_mo.providers import register_mock_provider_routes
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


@dataclass
class InProcessMoBridgeClient:
    client: TestClient
    last_embedding_response: dict[str, Any] | None = None
    last_generation_response: dict[str, Any] | None = None

    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/embeddings",
            json={"alias": alias, "inputs": inputs},
            headers=service_headers("nex-cx", "nex-mo", trace_id, request_id),
        )
        if response.status_code >= 400:
            body = response.json()
            raise EmbeddingIndexError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.embedding_request_failed"),
                detail=body.get("detail", "MO embedding request failed."),
                retryable=body.get("retryable", False),
            )
        self.last_embedding_response = response.json()
        return self.last_embedding_response

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/generations",
            json=payload,
            headers=service_headers("nex-cx", "nex-mo", trace_id, request_id),
        )
        if response.status_code >= 400:
            body = response.json()
            raise GenerationFacadeError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.request_failed"),
                detail=body.get("detail", "MO generation request failed."),
                retryable=body.get("retryable", False),
            )
        self.last_generation_response = response.json()
        return self.last_generation_response


@pytest.fixture(autouse=True)
def reset_provider_telemetry():
    remote_provider.reset_remote_provider_telemetry()
    yield
    remote_provider.reset_remote_provider_telemetry()


def test_cx_embedding_and_generation_bridge_to_mo_live_remote_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    configure_mo_live_env(monkeypatch)

    def fake_remote_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/v1/embeddings"):
            inputs = kwargs["json"]["input"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [float(index), 0.25, 0.75]}
                        for index, _ in enumerate(inputs)
                    ],
                    "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "cmpl-bridge-001",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Remote bridge answer.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 3,
                    "total_tokens": 7,
                },
            },
        )

    monkeypatch.setattr(remote_provider.httpx, "request", fake_remote_request)
    cx_client, mo_client, mo_test_client, generation_store = build_bridge_clients(tmp_path)

    uploaded = register_document(cx_client)
    run_cx_post(cx_client, f"/api/v1/jobs/{uploaded['extraction']['job_id']}/run")
    run_cx_post(cx_client, f"/api/v1/documents/{uploaded['document_id']}/chunks/run")
    embedding_index = run_cx_post(
        cx_client,
        f"/api/v1/documents/{uploaded['document_id']}/embeddings/run",
    )
    generation = cx_client.post(
        "/api/v1/generations",
        json={
            "prompt": "Use the live bridge provider.",
            "alias": "general-llm-default",
            "provider_capability": "generation",
        },
        headers=service_headers("nex-ae-api", "nex-cx"),
    )
    telemetry = mo_test_client.get(
        "/api/v1/provider-telemetry",
        headers=service_headers("nex-cx", "nex-mo"),
    )

    assert generation.status_code == 200
    generation_payload = generation.json()
    assert embedding_index["model_revision"] == "BridgeEmbedding"
    assert embedding_index["deployment_id"] == "remote-embedding-http"
    assert generation_payload["mo_generation_id"] == "cmpl-bridge-001"
    assert generation_payload["response_metadata"]["output_preview"] == (
        "Remote bridge answer."
    )
    assert generation_payload["mo_runtime_metadata"]["provider_request_id"] == (
        "cmpl-bridge-001"
    )
    assert generation_store.get(generation_payload["cx_generation_id"]) == generation_payload
    assert mo_client.last_embedding_response is not None
    assert mo_client.last_generation_response is not None
    assert [call["url"] for call in calls] == [
        "http://remote-provider.test/v1/embeddings",
        "http://remote-provider.test/v1/chat/completions",
    ]
    assert telemetry.status_code == 200
    telemetry_rows = {
        item["capability"]: item for item in telemetry.json()["data"]
    }
    assert telemetry_rows["embedding"]["request_count"] == 1
    assert telemetry_rows["generation"]["request_count"] == 1
    assert telemetry_rows["generation"]["success_count"] == 1
    assert "remote-provider.test" not in str(embedding_index)
    assert "remote-provider.test" not in str(generation_payload)
    assert "remote-provider.test" not in str(telemetry.json())


def test_cx_generation_bridge_preserves_mo_remote_failure_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_mo_live_env(monkeypatch)

    def throttled_remote_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(429, json={"error": "throttled"})

    monkeypatch.setattr(remote_provider.httpx, "request", throttled_remote_request)
    cx_client, _, mo_test_client, generation_store = build_bridge_clients(tmp_path)
    response = cx_client.post(
        "/api/v1/generations",
        json={
            "prompt": "This should be safely throttled.",
            "alias": "general-llm-default",
            "provider_capability": "generation",
        },
        headers=service_headers("nex-ae-api", "nex-cx"),
    )
    telemetry = mo_test_client.get(
        "/api/v1/provider-telemetry",
        headers=service_headers("nex-cx", "nex-mo"),
    ).json()

    assert response.status_code == 429
    assert response.json()["error_code"] == "mo.remote_generation_throttled"
    assert response.json()["retryable"] is True
    assert len(generation_store.records) == 1
    failed_record = next(iter(generation_store.records.values()))
    assert failed_record["status"] == "FAILED"
    assert failed_record["failure"]["failure_code"] == "mo.remote_generation_throttled"
    assert failed_record["failure"]["retryable"] is True
    assert "This should be safely throttled." not in str(failed_record)

    generation_row = [
        item for item in telemetry["data"] if item["capability"] == "generation"
    ][0]
    assert generation_row["failure_count"] == 1
    assert generation_row["retryable_failure_count"] == 1
    assert generation_row["degraded_count"] == 1
    assert generation_row["last_error_code"] == "mo.remote_generation_throttled"
    assert generation_row["last_failure_kind"] == "throttled"
    assert "remote-provider.test" not in str(telemetry)


def build_bridge_clients(
    tmp_path: Path,
) -> tuple[TestClient, TestClientMoBridgeClient, TestClient, GenerationExecutionStore]:
    mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
    register_mock_provider_routes(mo_app)
    mo_test_client = TestClient(mo_app)
    mo_bridge_client = InProcessMoBridgeClient(mo_test_client)

    cx_store = ContentIngestionStore()
    generation_store = GenerationExecutionStore()
    cx_app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_ingestion_routes(
        cx_app,
        store=cx_store,
        storage_config=storage_config(tmp_path),
    )
    register_chunking_routes(
        cx_app,
        store=cx_store,
        storage_config=storage_config(tmp_path),
    )
    register_embedding_index_routes(
        cx_app,
        store=cx_store,
        mo_client=mo_bridge_client,
        embedding_alias=DEFAULT_EMBEDDING_ALIAS,
    )
    register_generation_routes(
        cx_app,
        store=generation_store,
        mo_client=mo_bridge_client,
    )
    return TestClient(cx_app), mo_bridge_client, mo_test_client, generation_store


def configure_mo_live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEX_MO_PROVIDER_MODE", "live")
    monkeypatch.setenv(
        "NEX_MO_REMOTE_EMBEDDING_URL",
        "http://remote-provider.test/v1/embeddings",
    )
    monkeypatch.setenv("NEX_MO_REMOTE_EMBEDDING_MODEL", "BridgeEmbedding")
    monkeypatch.setenv(
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
        "http://remote-provider.test/v1/chat/completions",
    )
    monkeypatch.setenv("NEX_MO_VLLM_MODEL", "BridgeGeneration")


def storage_config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "source-files",
        extracted_markdown_root=tmp_path / "extracted-markdown",
        extraction_temp_root=tmp_path / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def register_document(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "trace_id": TRACE_ID,
            "filename": "bridge-source.md",
            "content_type": "text/markdown",
            "content_text": "Remote bridge source document for CX to MO regression.",
        },
        headers=service_headers("nex-ae-api", "nex-cx"),
    )
    response.raise_for_status()
    return response.json()


def run_cx_post(client: TestClient, path: str) -> dict[str, Any]:
    response = client.post(path, headers=service_headers("nex-ae-api", "nex-cx"))
    response.raise_for_status()
    return response.json()


def service_headers(
    service_id: str,
    audience: str,
    trace_id: str = TRACE_ID,
    request_id: str = REQUEST_ID,
) -> dict[str, str]:
    token = issue_mock_service_token(service_id=service_id, audience=audience).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Service-ID": service_id,
    }
