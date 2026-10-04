#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence, cast

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-cx",
    ROOT / "services" / "nex-mo",
    ROOT / "services" / "_shared",
):
    sys.path.insert(0, str(path))

from nex_cx.ingestion import (  # noqa: E402
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
)
from nex_cx.chunking import build_and_store_chunk_set  # noqa: E402
from nex_cx.lexical_index import build_and_store_lexical_index  # noqa: E402
from nex_cx.mvp_ingestion_indexing import MvpIngestionVectorIndexer  # noqa: E402
from nex_cx.private_content import (  # noqa: E402
    build_private_payload_receipt,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.repository import InMemoryCxContentRepository  # noqa: E402
from nex_cx.vector_index_freshness import (  # noqa: E402
    build_vector_payload_snapshot,
)
from nex_cx.vector_index_operations import get_vector_index_readiness  # noqa: E402
from nex_cx.vector_index_repository import InMemoryVectorIndexRepository  # noqa: E402
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


SCHEMA_VERSION = "cx_mock_vector_publish_freshness_evidence.v1"
PRIVATE_SOURCE = "S135_PRIVATE_VECTOR_SOURCE alpha beta gamma delta epsilon"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TENANT_ID = "tenant-1347"
OWNER_ID = "owner-1347"


class ProtectedMockMoEmbeddingClient:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.calls = 0
        self.input_count = 0
        self.token = issue_mock_service_token(
            service_id="nex-cx",
            audience="nex-mo",
        ).access_token

    def create_embeddings(
        self,
        inputs: list[str],
        *,
        alias: str,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls += 1
        self.input_count += len(inputs)
        response = self.client.post(
            "/api/v1/embeddings",
            json={"alias": alias, "inputs": inputs},
            headers={
                "Authorization": f"Bearer {self.token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
            },
        )
        response.raise_for_status()
        return response.json()


class MemoryBoundVectorStore:
    def __init__(self, manifest: Mapping[str, Any]) -> None:
        self.manifest = dict(manifest)
        self.receipts: dict[str, dict[str, Any]] = {}

    def put_vector(
        self,
        *,
        access_context,
        key,
        vector: Sequence[float],
        expected_sha256: str,
    ):
        if access_context.ownership_key != (
            self.manifest["tenant_ref"]["id"],
            self.manifest["owner_subject_ref"]["id"],
        ):
            raise AssertionError("owner scope mismatch")
        receipt = build_private_payload_receipt(
            key=key,
            storage_backend="memory-vector-evidence-v1",
            storage_uri=f"cx-private://memory/{key.content_id}",
            sha256=expected_sha256,
            size_bytes=len(vector) * 8,
            vector_dimension=len(vector),
        )
        self.receipts[key.content_id] = {
            "chunk_id": key.content_id,
            "embedding_sha256": receipt.sha256,
            "vector_dimension": receipt.vector_dimension,
            "storage_uri": receipt.storage_uri,
        }
        return receipt

    def delete_vector(self, *, access_context, key) -> bool:
        return self.receipts.pop(key.content_id, None) is not None

    def payload_snapshot(self, *, access_context) -> dict[str, Any]:
        if access_context.ownership_key != (
            self.manifest["tenant_ref"]["id"],
            self.manifest["owner_subject_ref"]["id"],
        ):
            raise AssertionError("owner scope mismatch")
        return build_vector_payload_snapshot(list(self.receipts.values()))


class MemoryVectorStore:
    def __init__(self) -> None:
        self.bound: dict[str, MemoryBoundVectorStore] = {}

    def bind_index(self, manifest: Mapping[str, Any]) -> MemoryBoundVectorStore:
        index_id = str(manifest["vector_index_id"])
        return self.bound.setdefault(index_id, MemoryBoundVectorStore(manifest))


def run_cx_mock_vector_publish_freshness() -> dict[str, Any]:
    repository = InMemoryCxContentRepository()
    vector_repository = InMemoryVectorIndexRepository()
    vector_store = MemoryVectorStore()
    mo_app = build_service_app(SERVICE_SPECS["nex-mo"])
    register_mock_provider_routes(mo_app)

    with TemporaryDirectory(prefix="nex-s135-1347-") as data_root:
        config = _storage_config(Path(data_root))
        store = ContentIngestionStore(content_repository=repository)
        saved = store.save_upload_registration(
            build_upload_registration(
                {
                    "filename": "private-vector.md",
                    "content_type": "text/markdown",
                    "content_text": PRIVATE_SOURCE,
                    "tenant_id": TENANT_ID,
                    "owner_user_id": OWNER_ID,
                },
                storage_config=config,
                request_id="request-1347",
                trace_id=TRACE_ID,
            ),
            source_text=PRIVATE_SOURCE,
        )
        extraction = run_text_extraction_job(
            saved["ingestion_job"]["job_id"],
            store=store,
            storage_config=config,
            request_id="request-1347",
            trace_id=TRACE_ID,
        )
        chunk_set = build_and_store_chunk_set(
            saved["document_id"],
            store=store,
            storage_config=config,
            request_id="request-1347",
            trace_id=TRACE_ID,
        )
        lexical = build_and_store_lexical_index(
            saved["document_id"],
            store=store,
            storage_config=config,
            request_id="request-1347",
            trace_id=TRACE_ID,
        )
        with TestClient(mo_app) as mo_client:
            embedding_client = ProtectedMockMoEmbeddingClient(mo_client)
            indexer = MvpIngestionVectorIndexer(
                store=store,
                private_text_store=FileSystemCxPrivateTextStore(
                    Path(data_root) / "private-text"
                ),
                embedding_client=embedding_client,
                embedding_alias="mock-embedding-default",
                vector_repository=vector_repository,
                vector_store=vector_store,
            )
            result = indexer(
                {
                    "document_id": saved["document_id"],
                    "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
                    "owner_subject_ref": {"type": "oa.user", "id": OWNER_ID},
                    "request_id": "request-1347",
                    "trace_id": TRACE_ID,
                    "updated_at": extraction["updated_at"],
                }
            )

        vector_index_id = result.output_ref.split(":", 1)[1]
        manifest = cast(
            dict[str, Any],
            vector_repository.get(
                vector_index_id,
                tenant_id=TENANT_ID,
                owner_subject_id=OWNER_ID,
            ),
        )
        readiness = get_vector_index_readiness(
            access_context=_owner_context(),
            vector_index_id=vector_index_id,
            repository=vector_repository,
            vector_store=vector_store,
        )
        hidden = vector_repository.get(
            vector_index_id,
            tenant_id=TENANT_ID,
            owner_subject_id="other-owner",
        )

    evidence = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1347",
        "requirement": "S135",
        "provider_path": "cx_service_token_to_mo_mock_embedding",
        "provider_alias": manifest["embedding_profile"]["provider_alias"],
        "model_revision": manifest["embedding_profile"]["model_revision"],
        "vector_dimension": manifest["embedding_profile"]["vector_dimension"],
        "chunk_count": chunk_set["chunk_count"],
        "lexical_chunk_count": lexical["chunk_count"],
        "mo_call_count": embedding_client.calls,
        "mo_input_count": embedding_client.input_count,
        "readiness": readiness,
        "private_payload_in_evidence": False,
        "database_used": "in_memory_vector_regression",
        "actual_postgres_deferred_to": "1350",
        "next_slice": "1348",
    }
    serialized = json.dumps(evidence, sort_keys=True)
    checks = {
        "protected_mo_called_once": embedding_client.calls == 1,
        "all_chunks_embedded": embedding_client.input_count == chunk_set["chunk_count"],
        "mock_alias_recorded": evidence["provider_alias"]
        == "mock-embedding-default",
        "ready_manifest_persisted": manifest["status"] == "READY",
        "payload_count_complete": manifest["payload_count"]
        == chunk_set["chunk_count"],
        "payload_fingerprint_present": bool(manifest["payload_fingerprint"]),
        "freshness_ready": readiness["freshness_status"] == "READY",
        "retrieval_usable": readiness["retrieval_usable"] is True,
        "owner_scope_hidden": hidden is None,
        "lexical_precedes_vector": lexical["chunk_count"] == chunk_set["chunk_count"],
        "private_source_absent": PRIVATE_SOURCE not in serialized,
        "raw_vectors_absent": '"embedding":' not in serialized.lower(),
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        **evidence,
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
    }


def _owner_context():
    from nex_cx.access_context import CxAccessContext

    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id=TENANT_ID,
        subject_id=OWNER_ID,
        request_id="request-1347",
        trace_id=TRACE_ID,
        scopes=("service.invoke",),
    )


def _storage_config(data_root: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=data_root,
        source_root=data_root / "source-files",
        extracted_markdown_root=data_root / "extracted-markdown",
        extraction_temp_root=data_root / "temp",
        chunk_policy="chunk_24_4",
        chunk_size=24,
        chunk_overlap=4,
        bm25_tokenizer="korean_mixed_v1",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"cx_mock_vector_publish=fail issues={len(evidence.get('issues') or [])}"
    checks = evidence.get("checks") or {}
    readiness = evidence.get("readiness") or {}
    return (
        "cx_mock_vector_publish=pass "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"chunks={evidence.get('chunk_count')} freshness={readiness.get('freshness_status')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_mock_vector_publish_freshness()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
