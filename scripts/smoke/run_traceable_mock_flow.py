from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[2]
for service_path in (
    "services/_shared",
    "services/nex-oa",
    "services/nex-ag",
    "services/nex-ae-api",
    "services/nex-cx",
    "services/nex-mo",
):
    sys.path.insert(0, str(ROOT_DIR / service_path))

from nex_ae_api.chat import ChatInteractionStore, register_chat_routes
from nex_ag.readiness import register_readiness_routes
from nex_cx.chunking import register_chunking_routes
from nex_cx.embedding_index import (
    DEFAULT_EMBEDDING_ALIAS,
    register_embedding_index_routes,
)
from nex_cx.generation import GenerationExecutionStore, register_generation_routes
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    register_ingestion_routes,
)
from nex_cx.lexical_index import register_lexical_index_routes
from nex_cx.retrieval import register_retrieval_routes
from nex_mo.providers import register_mock_provider_routes
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
SMOKE_TEXT = (
    "Traceable retrieval smoke evidence confirms that uploaded source text is "
    "extracted to Markdown, chunked with chunk_1000_100, indexed for embedding "
    "and lexical retrieval, then used as grounded evidence before generation."
)


@dataclass
class TestClientMoGenerationClient:
    client: TestClient
    last_response: dict[str, Any] | None = None
    last_embedding_response: dict[str, Any] | None = None

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
        response.raise_for_status()
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
        response.raise_for_status()
        self.last_response = response.json()
        return self.last_response


@dataclass
class TestClientCxRetrievalClient:
    client: TestClient
    last_response: dict[str, Any] | None = None

    def create_retrieval_context(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/retrieval/context",
            json=payload,
            headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
        )
        response.raise_for_status()
        self.last_response = response.json()
        return self.last_response


@dataclass
class TestClientCxGenerationClient:
    client: TestClient
    last_response: dict[str, Any] | None = None

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
            headers=service_headers("nex-ae-api", "nex-cx", trace_id, request_id),
        )
        response.raise_for_status()
        self.last_response = response.json()
        return self.last_response


class StaticReadinessStatusClient:
    def fetch_status(self, service_id: str, base_url: str) -> dict[str, Any]:
        return {
            "service_id": service_id,
            "base_url": base_url,
            "health_status": "HEALTHY",
            "readiness_status": "READY",
            "version": "0.0.0-smoke",
            "contract_catalog_version": "slice-0020",
            "observed_status": "READY",
            "failures": [],
        }


def run_traceable_mock_flow(trace_id: str = TRACE_ID) -> dict[str, Any]:
    request_id = REQUEST_ID

    with tempfile.TemporaryDirectory(prefix="nex-trace-smoke-") as temp_dir:
        storage_config = build_smoke_storage_config(Path(temp_dir))
        mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
        register_mock_provider_routes(mo_app)
        mo_client = TestClientMoGenerationClient(TestClient(mo_app))

        cx_store = ContentIngestionStore()
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
        register_embedding_index_routes(
            cx_app,
            store=cx_store,
            mo_client=mo_client,
            embedding_alias=DEFAULT_EMBEDDING_ALIAS,
        )
        register_lexical_index_routes(
            cx_app,
            store=cx_store,
            storage_config=storage_config,
        )
        register_retrieval_routes(cx_app, store=cx_store)
        register_generation_routes(
            cx_app,
            store=GenerationExecutionStore(),
            mo_client=mo_client,
            retrieval_store=cx_store,
        )
        cx_test_client = TestClient(cx_app)
        cx_client = TestClientCxGenerationClient(cx_test_client)
        retrieval_client = TestClientCxRetrievalClient(cx_test_client)

        cx_upload = register_smoke_document(cx_test_client, trace_id, request_id)
        cx_extraction = run_cx_post(
            cx_test_client,
            f"/api/v1/jobs/{cx_upload['extraction']['job_id']}/run",
            trace_id,
            request_id,
        )
        cx_chunk_set = run_cx_post(
            cx_test_client,
            f"/api/v1/documents/{cx_upload['document_id']}/chunks/run",
            trace_id,
            request_id,
        )
        cx_embedding_index = run_cx_post(
            cx_test_client,
            f"/api/v1/documents/{cx_upload['document_id']}/embeddings/run",
            trace_id,
            request_id,
        )
        cx_lexical_index = run_cx_post(
            cx_test_client,
            f"/api/v1/documents/{cx_upload['document_id']}/lexical-index/run",
            trace_id,
            request_id,
        )

        ae_app = build_service_app(SERVICE_SPECS["nex-ae-api"])
        register_chat_routes(
            ae_app,
            store=ChatInteractionStore(),
            cx_client=cx_client,
            retrieval_client=retrieval_client,
        )
        ae_response = TestClient(ae_app).post(
            "/api/v1/chat/interactions",
            json={
                "trace_id": trace_id,
                "user_message": "Summarize the traceable retrieval smoke evidence.",
                "retrieval": {
                    "purpose": "grounded_answer",
                    "query_text": "traceable retrieval smoke evidence",
                    "document_scope": {"document_ids": [cx_upload["document_id"]]},
                    "top_k": 2,
                    "include_source_preview": True,
                },
            },
            headers=service_headers("nex-oa", "nex-ae-api", trace_id, request_id),
        )
        ae_response.raise_for_status()

        ag_app = build_service_app(SERVICE_SPECS["nex-ag"])
        register_readiness_routes(
            ag_app,
            status_client=StaticReadinessStatusClient(),
            service_endpoints={
                service_id: f"http://127.0.0.1:{spec.default_port}"
                for service_id, spec in SERVICE_SPECS.items()
            },
        )
        ag_response = TestClient(ag_app).get(
            "/admin/v1/readiness/services",
            headers=service_headers("nex-oa", "nex-ag", trace_id, request_id),
        )
        ag_response.raise_for_status()

        evidence = {
            "trace_id": trace_id,
            "request_id": request_id,
            "cx_upload": cx_upload,
            "cx_extraction": cx_extraction,
            "cx_chunk_set": cx_chunk_set,
            "cx_embedding_index": cx_embedding_index,
            "cx_lexical_index": cx_lexical_index,
            "cx_retrieval": retrieval_client.last_response,
            "ae": ae_response.json(),
            "cx": cx_client.last_response,
            "mo_embedding": mo_client.last_embedding_response,
            "mo": mo_client.last_response,
            "ag": ag_response.json(),
        }
    evidence["assertions"] = assert_trace_evidence(evidence)
    return evidence


def assert_trace_evidence(evidence: dict[str, Any]) -> dict[str, bool]:
    trace_id = evidence["trace_id"]
    assertions = {
        "cx_upload_trace": evidence["cx_upload"]["trace_id"] == trace_id,
        "cx_extraction_trace": evidence["cx_extraction"]["trace_id"] == trace_id,
        "cx_chunk_trace": evidence["cx_chunk_set"]["trace_id"] == trace_id,
        "cx_embedding_trace": evidence["cx_embedding_index"]["trace_id"] == trace_id,
        "cx_lexical_trace": evidence["cx_lexical_index"]["trace_id"] == trace_id,
        "cx_retrieval_trace": evidence["cx_retrieval"]["trace_id"] == trace_id,
        "ae_trace": evidence["ae"]["trace_id"] == trace_id,
        "cx_generation_trace": evidence["cx"]["trace_id"] == trace_id,
        "mo_generation_trace": evidence["mo"]["runtime_metadata"]["trace_id"] == trace_id,
        "ag_trace": evidence["ag"]["trace_id"] == trace_id,
        "retrieval_lineage": evidence["ae"]["retrieval"]["cx_retrieval_package_id"]
        == evidence["cx_retrieval"]["retrieval_package_id"],
        "generation_lineage": evidence["ae"]["cx_generation_id"]
        == evidence["cx"]["cx_generation_id"],
        "mo_lineage": evidence["cx"]["mo_generation_id"]
        == evidence["mo"]["mo_generation_id"],
        "indexed_document_lineage": evidence["cx_upload"]["document_id"]
        == evidence["cx_embedding_index"]["document_id"]
        == evidence["cx_lexical_index"]["document_id"],
    }
    if not all(assertions.values()):
        raise AssertionError(f"trace evidence mismatch: {assertions}")
    return assertions


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
            "filename": "traceable-smoke.md",
            "content_type": "text/markdown",
            "content_text": SMOKE_TEXT,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the grounded traceable mock flow.")
    parser.add_argument("--summary", action="store_true", help="Print a short pass line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_traceable_mock_flow()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.summary:
        print(
            "traceable_mock_flow=pass "
            f"trace_id={evidence['trace_id']} "
            f"doc={evidence['cx_upload']['document_id']} "
            f"retrieval={evidence['cx_retrieval']['retrieval_package_id']} "
            f"ae={evidence['ae']['interaction_id']} "
            f"cx={evidence['cx']['cx_generation_id']} "
            f"mo={evidence['mo']['mo_generation_id']} "
            f"ag_services={evidence['ag']['summary']['total']}"
        )
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
