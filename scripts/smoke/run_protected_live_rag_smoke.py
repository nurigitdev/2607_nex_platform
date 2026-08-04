#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[2]
for service_path in (
    "services/_shared",
    "services/nex-cx",
    "services/nex-mo",
    "scripts/smoke",
):
    sys.path.insert(0, str(ROOT_DIR / service_path))

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
from nex_cx.lexical_index import register_lexical_index_routes
from nex_cx.retrieval import (
    DEFAULT_RERANKER_ALIAS,
    RetrievalError,
    register_retrieval_routes,
)
from nex_mo.providers import register_mock_provider_routes
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
LIVE_RAG_SMOKE_ENV = "NEX_PROTECTED_LIVE_RAG_SMOKE"
PROFILE_ENV = "NEX_PROTECTED_LIVE_RAG_PROFILE"
DEFAULT_PROFILE = "dgx_vllm"
SMOKE_TEXT = (
    "Protected live RAG smoke evidence verifies that CX can upload a source "
    "document, build lexical and embedding indexes, rerank retrieval evidence, "
    "and complete grounded generation through MO live provider mode."
)
PROTECTED_LIVE_RAG_ENV_KEYS = (
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
    "NEX_MO_LIVE_RERANKER_HEALTH_URL",
    "NEX_MO_LIVE_VLLM_MODELS_URL",
)

HttpRequester = Callable[..., httpx.Response]


@dataclass
class InProcessLiveMoClient:
    client: TestClient
    last_embedding_response: dict[str, Any] | None = None
    last_rerank_response: dict[str, Any] | None = None
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
            body = _safe_response_json(response)
            raise EmbeddingIndexError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.embedding_request_failed"),
                detail=body.get("detail", "MO embedding request failed."),
                retryable=body.get("retryable", False),
            )
        self.last_embedding_response = response.json()
        return self.last_embedding_response

    def rerank_documents(
        self,
        query: str,
        documents: list[str],
        *,
        alias: str,
        top_n: int,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/rerank",
            json={
                "alias": alias,
                "query": query,
                "documents": documents,
                "top_n": top_n,
            },
            headers=service_headers("nex-cx", "nex-mo", trace_id, request_id),
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise RetrievalError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.rerank_request_failed"),
                detail=body.get("detail", "MO rerank request failed."),
                retryable=body.get("retryable", False),
            )
        self.last_rerank_response = response.json()
        return self.last_rerank_response

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
            body = _safe_response_json(response)
            raise GenerationFacadeError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.request_failed"),
                detail=body.get("detail", "MO generation request failed."),
                retryable=body.get("retryable", False),
            )
        self.last_generation_response = response.json()
        return self.last_generation_response


def run_protected_live_rag_smoke(
    environ: dict[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
    trace_id: str = TRACE_ID,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(LIVE_RAG_SMOKE_ENV) != "1":
        return build_protected_live_rag_evidence(
            status="SKIPPED",
            env=env,
            effective_env=env,
            stage_status={"activation": "SKIPPED"},
            rag_evidence=None,
            issues=[
                {
                    "stage": "activation",
                    "error_code": "protected_live_rag_smoke_not_enabled",
                    "detail": f"{LIVE_RAG_SMOKE_ENV} is not enabled.",
                }
            ],
        )

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    config_issues = protected_live_rag_config_issues(effective_env)
    if config_issues:
        return build_protected_live_rag_evidence(
            status="FAIL",
            env=env,
            effective_env=effective_env,
            stage_status={"activation": "PASS", "configuration": "FAIL"},
            rag_evidence=None,
            issues=config_issues,
        )

    try:
        with patched_environ(effective_env):
            with patched_remote_request(requester):
                remote_provider.reset_remote_provider_telemetry()
                rag_evidence = run_live_rag_flow(trace_id=trace_id)
        return build_protected_live_rag_evidence(
            status="PASS",
            env=env,
            effective_env=effective_env,
            stage_status={
                "activation": "PASS",
                "configuration": "PASS",
                "rag_flow": "PASS",
            },
            rag_evidence=rag_evidence,
            issues=[],
        )
    except Exception as exc:
        return build_protected_live_rag_evidence(
            status="FAIL",
            env=env,
            effective_env=effective_env,
            stage_status={
                "activation": "PASS",
                "configuration": "PASS",
                "rag_flow": "FAIL",
            },
            rag_evidence=None,
            issues=[
                {
                    "stage": "rag_flow",
                    "error_code": exc.__class__.__name__,
                    "detail": "Protected live RAG smoke flow failed.",
                }
            ],
        )


def run_live_rag_flow(*, trace_id: str) -> dict[str, Any]:
    request_id = REQUEST_ID
    with tempfile.TemporaryDirectory(prefix="nex-live-rag-smoke-") as temp_dir:
        storage_config = build_smoke_storage_config(Path(temp_dir))
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        mo_test_client = TestClient(mo_app)
        mo_client = InProcessLiveMoClient(mo_test_client)

        cx_store = ContentIngestionStore()
        generation_store = GenerationExecutionStore()
        cx_app = build_service_app(SERVICE_SPECS["nex-cx"])
        register_ingestion_routes(
            cx_app,
            store=cx_store,
            storage_config=storage_config,
        )
        register_chunking_routes(
            cx_app,
            store=cx_store,
            storage_config=storage_config,
        )
        register_lexical_index_routes(
            cx_app,
            store=cx_store,
            storage_config=storage_config,
        )
        register_embedding_index_routes(
            cx_app,
            store=cx_store,
            mo_client=mo_client,
            embedding_alias=DEFAULT_EMBEDDING_ALIAS,
        )
        register_retrieval_routes(
            cx_app,
            store=cx_store,
            rerank_client=mo_client,
            reranker_alias=DEFAULT_RERANKER_ALIAS,
        )
        register_generation_routes(
            cx_app,
            store=generation_store,
            mo_client=mo_client,
            retrieval_store=cx_store,
        )
        cx_client = TestClient(cx_app)

        upload = register_smoke_document(cx_client, trace_id, request_id)
        extraction = run_cx_post(
            cx_client,
            f"/api/v1/jobs/{upload['extraction']['job_id']}/run",
            trace_id,
            request_id,
        )
        chunk_set = run_cx_post(
            cx_client,
            f"/api/v1/documents/{upload['document_id']}/chunks/run",
            trace_id,
            request_id,
        )
        lexical_index = run_cx_post(
            cx_client,
            f"/api/v1/documents/{upload['document_id']}/lexical-index/run",
            trace_id,
            request_id,
        )
        embedding_index = run_cx_post(
            cx_client,
            f"/api/v1/documents/{upload['document_id']}/embeddings/run",
            trace_id,
            request_id,
        )
        retrieval = create_retrieval_context(
            cx_client,
            document_id=upload["document_id"],
            trace_id=trace_id,
            request_id=request_id,
        )
        generation = create_grounded_generation(
            cx_client,
            retrieval_package=retrieval,
            trace_id=trace_id,
            request_id=request_id,
        )
        telemetry = read_provider_telemetry(mo_test_client, trace_id, request_id)

    return build_rag_evidence_summary(
        trace_id=trace_id,
        request_id=request_id,
        upload=upload,
        extraction=extraction,
        chunk_set=chunk_set,
        lexical_index=lexical_index,
        embedding_index=embedding_index,
        retrieval=retrieval,
        generation=generation,
        telemetry=telemetry,
    )


def protected_live_rag_config_issues(env: dict[str, str]) -> list[dict[str, str]]:
    checks = {
        "NEX_MO_REMOTE_EMBEDDING_URL": bool(env.get("NEX_MO_REMOTE_EMBEDDING_URL")),
        "NEX_MO_REMOTE_RERANKER_URL": bool(env.get("NEX_MO_REMOTE_RERANKER_URL")),
        "NEX_MO_VLLM_GENERATION_URL": bool(
            env.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL")
            or env.get("NEX_MO_VLLM_BASE_URL")
        ),
    }
    issues = [
        {
            "stage": "configuration",
            "error_code": "provider_endpoint_missing",
            "detail": f"{key} is required for protected live RAG smoke.",
        }
        for key, configured in checks.items()
        if not configured
    ]
    if env.get("NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE") != "openai_embeddings":
        issues.append(
            {
                "stage": "configuration",
                "error_code": "embedding_request_shape_not_compatible",
                "detail": "Embedding request shape must be openai_embeddings.",
            }
        )
    if env.get("NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE") != "rerank":
        issues.append(
            {
                "stage": "configuration",
                "error_code": "reranker_request_shape_not_compatible",
                "detail": "Reranker request shape must be rerank.",
            }
        )
    return issues


def build_rag_evidence_summary(
    *,
    trace_id: str,
    request_id: str,
    upload: dict[str, Any],
    extraction: dict[str, Any],
    chunk_set: dict[str, Any],
    lexical_index: dict[str, Any],
    embedding_index: dict[str, Any],
    retrieval: dict[str, Any],
    generation: dict[str, Any],
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    assertions = assert_live_rag_evidence(
        trace_id=trace_id,
        upload=upload,
        extraction=extraction,
        chunk_set=chunk_set,
        lexical_index=lexical_index,
        embedding_index=embedding_index,
        retrieval=retrieval,
        generation=generation,
        telemetry=telemetry,
    )
    return {
        "rag_schema_version": "protected_live_rag_smoke.v1",
        "trace_id": trace_id,
        "request_id": request_id,
        "document": {
            "document_id": upload["document_id"],
            "source_sha256": upload["source_sha256"],
            "extraction_job_id": extraction["job_id"],
            "chunk_count": chunk_set["chunk_count"],
            "embedding_dimension": embedding_index["vector_dimension"],
            "tokenizer_used": lexical_index["tokenizer_used"],
        },
        "retrieval": {
            "retrieval_package_id": retrieval["retrieval_package_id"],
            "package_hash": retrieval["package_hash"],
            "status": retrieval["status"],
            "evidence_count": len(retrieval["evidence_items"]),
            "rerank_state": retrieval["score_summary"]["rerank_state"],
            "ranker_mix": retrieval["score_summary"]["ranker_mix"],
            "quality_policy_id": retrieval["score_summary"]["quality_policy_id"],
            "best_score": retrieval["score_summary"]["best_score"],
        },
        "generation": {
            "cx_generation_id": generation["cx_generation_id"],
            "mo_generation_id": generation["mo_generation_id"],
            "status": generation["status"],
            "finish_reason": generation["response_metadata"]["finish_reason"],
            "compatibility_rule_id": generation["request_metadata"][
                "compatibility_rule_id"
            ],
            "selected_evidence_count": generation["request_metadata"][
                "selected_evidence_count"
            ],
            "draft_validation_status": generation["request_metadata"][
                "draft_validation_status"
            ],
        },
        "provider_telemetry": telemetry,
        "assertions": assertions,
    }


def assert_live_rag_evidence(
    *,
    trace_id: str,
    upload: dict[str, Any],
    extraction: dict[str, Any],
    chunk_set: dict[str, Any],
    lexical_index: dict[str, Any],
    embedding_index: dict[str, Any],
    retrieval: dict[str, Any],
    generation: dict[str, Any],
    telemetry: dict[str, Any],
) -> dict[str, bool]:
    telemetry_by_capability = {
        item["capability"]: item for item in telemetry.get("data", [])
    }
    assertions = {
        "upload_trace": upload["trace_id"] == trace_id,
        "extraction_trace": extraction["trace_id"] == trace_id,
        "chunk_trace": chunk_set["trace_id"] == trace_id,
        "lexical_trace": lexical_index["trace_id"] == trace_id,
        "embedding_trace": embedding_index["trace_id"] == trace_id,
        "retrieval_trace": retrieval["trace_id"] == trace_id,
        "generation_trace": generation["trace_id"] == trace_id,
        "document_lineage": upload["document_id"]
        == extraction["document_id"]
        == chunk_set["document_id"]
        == lexical_index["document_id"]
        == embedding_index["document_id"],
        "retrieval_ready": retrieval["status"] == "READY",
        "rerank_applied": retrieval["score_summary"]["rerank_state"] == "APPLIED",
        "grounded_generation_completed": generation["status"] == "COMPLETED",
        "retrieval_lineage": generation["request_metadata"]["retrieval_package_id"]
        == retrieval["retrieval_package_id"],
        "embedding_live_call": telemetry_by_capability["embedding"]["success_count"] >= 1,
        "rerank_live_call": telemetry_by_capability["reranking"]["success_count"] >= 1,
        "generation_live_call": telemetry_by_capability["generation"]["success_count"] >= 1,
    }
    if not all(assertions.values()):
        raise AssertionError(f"protected live RAG evidence mismatch: {assertions}")
    return assertions


def build_protected_live_rag_evidence(
    *,
    status: str,
    env: dict[str, str],
    effective_env: dict[str, str],
    stage_status: dict[str, str],
    rag_evidence: dict[str, Any] | None,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence = {
        "evidence_schema_version": "protected_live_rag_smoke_evidence.v1",
        "evidence_generated_at": _utc_now(),
        "status": status,
        "activation": {
            "env": LIVE_RAG_SMOKE_ENV,
            "enabled": env.get(LIVE_RAG_SMOKE_ENV) == "1",
            "profile_env": PROFILE_ENV,
            "requested_profile": env.get(PROFILE_ENV, DEFAULT_PROFILE),
            "required_profile": DEFAULT_PROFILE,
        },
        "effective_flags": {
            "NEX_MO_PROVIDER_MODE": effective_env.get("NEX_MO_PROVIDER_MODE"),
            "embedding_request_shape": effective_env.get(
                "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE"
            ),
            "reranker_request_shape": effective_env.get(
                "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE"
            ),
            "generation_request_shape": "openai_chat_completions",
        },
        "provider_config": {
            "embedding": {
                "configured": bool(effective_env.get("NEX_MO_REMOTE_EMBEDDING_URL")),
                "model": effective_env.get("NEX_MO_REMOTE_EMBEDDING_MODEL"),
                "api_key_configured": bool(
                    effective_env.get("NEX_MO_REMOTE_EMBEDDING_API_KEY")
                ),
            },
            "reranking": {
                "configured": bool(effective_env.get("NEX_MO_REMOTE_RERANKER_URL")),
                "model": effective_env.get("NEX_MO_REMOTE_RERANKER_MODEL"),
                "api_key_configured": bool(
                    effective_env.get("NEX_MO_REMOTE_RERANKER_API_KEY")
                ),
            },
            "generation": {
                "configured": bool(
                    effective_env.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL")
                    or effective_env.get("NEX_MO_VLLM_BASE_URL")
                ),
                "model": effective_env.get("NEX_MO_VLLM_MODEL"),
                "api_key_configured": bool(effective_env.get("NEX_MO_VLLM_API_KEY")),
            },
        },
        "stage_status": stage_status,
        "rag_evidence": rag_evidence,
        "issues": issues,
        "redaction": {
            "status": "PASS",
            "policy": "provider endpoints and credentials are excluded",
            "checked_env_keys": [
                key for key in PROTECTED_LIVE_RAG_ENV_KEYS if env.get(key)
            ],
        },
    }
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    assert_protected_live_rag_evidence_redacted(serialized, env)
    return evidence


def build_smoke_storage_config(root: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=root,
        source_root=root / "source-files",
        extracted_markdown_root=root / "extracted-markdown",
        extraction_temp_root=root / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def register_smoke_document(
    client: TestClient,
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/documents/uploads",
        json={
            "trace_id": trace_id,
            "filename": "protected-live-rag-smoke.md",
            "content_type": "text/markdown",
            "content_text": SMOKE_TEXT,
        },
        headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
    )
    response.raise_for_status()
    return response.json()


def create_retrieval_context(
    client: TestClient,
    *,
    document_id: str,
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/retrieval/context",
        json={
            "trace_id": trace_id,
            "query_text": "protected live RAG smoke evidence",
            "purpose": "grounded_answer",
            "document_scope": {"document_ids": [document_id]},
            "top_k": 1,
            "include_source_preview": True,
            "retrieval_policy": {"rerank_candidate_limit": 5},
        },
        headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
    )
    response.raise_for_status()
    return response.json()


def create_grounded_generation(
    client: TestClient,
    *,
    retrieval_package: dict[str, Any],
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    evidence_id = retrieval_package["evidence_items"][0]["evidence_id"]
    response = client.post(
        "/api/v1/generations",
        json={
            "trace_id": trace_id,
            "messages": [
                {
                    "role": "user",
                    "content": "Answer using the selected protected live RAG evidence.",
                }
            ],
            "execution_mode": "GROUNDED_ANSWER",
            "template_id": "none",
            "prompt_binding_id": "ae.grounded_chat.default",
            "output_contract_id": "text_answer_v1",
            "provider_capability": "generation",
            "generation_profile": "grounded-answer",
            "retrieval_package_ref": {
                "retrieval_package_id": retrieval_package["retrieval_package_id"],
                "package_hash": retrieval_package["package_hash"],
            },
            "selected_evidence_ids": [evidence_id],
        },
        headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
    )
    response.raise_for_status()
    return response.json()


def run_cx_post(
    client: TestClient,
    path: str,
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.post(
        path,
        headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
    )
    response.raise_for_status()
    return response.json()


def read_provider_telemetry(
    client: TestClient,
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.get(
        "/api/v1/provider-telemetry",
        headers=service_headers("nex-cx", "nex-mo", trace_id, request_id),
    )
    response.raise_for_status()
    return response.json()


def service_headers(
    service_id: str,
    audience: str,
    trace_id: str,
    request_id: str,
) -> dict[str, str]:
    token = issue_mock_service_token(service_id=service_id, audience=audience).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
        "X-Service-ID": service_id,
    }


def write_protected_live_rag_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    assert_protected_live_rag_evidence_redacted(serialized, os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def assert_protected_live_rag_evidence_redacted(
    serialized_evidence: str,
    environ: dict[str, str],
) -> None:
    leaked_keys = [
        key
        for key in PROTECTED_LIVE_RAG_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked_keys:
        raise ValueError(
            "protected live RAG smoke evidence contains unredacted environment "
            f"value: {leaked_keys[0]}"
        )


@contextmanager
def patched_environ(env: dict[str, str]) -> Iterator[None]:
    original = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


@contextmanager
def patched_remote_request(requester: HttpRequester | None) -> Iterator[None]:
    if requester is None:
        yield
        return
    original_request = remote_provider.httpx.request
    remote_provider.httpx.request = requester
    try:
        yield
    finally:
        remote_provider.httpx.request = original_request


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"protected_live_rag_smoke=skipped reason={LIVE_RAG_SMOKE_ENV}"
    if evidence["status"] == "FAIL":
        failed_stages = [
            stage for stage, status in evidence["stage_status"].items() if status == "FAIL"
        ]
        return (
            "protected_live_rag_smoke=fail "
            f"failed_stages={','.join(failed_stages) or 'unknown'}"
        )
    rag = evidence["rag_evidence"]
    return (
        "protected_live_rag_smoke=pass "
        f"retrieval={rag['retrieval']['status']} "
        f"rerank={rag['retrieval']['rerank_state']} "
        f"generation={rag['generation']['status']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the protected live RAG smoke flow.")
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument(
        "--output",
        "--evidence-output",
        dest="output",
        type=Path,
        help="Optional protected JSON evidence output path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_protected_live_rag_smoke()
    if args.output:
        write_protected_live_rag_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _protected_env_value_leaked(
    serialized_evidence: str,
    value: str | None,
) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized_evidence


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
