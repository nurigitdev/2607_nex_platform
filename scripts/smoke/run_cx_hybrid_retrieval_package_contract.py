#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_cx.hybrid_retrieval_package import (  # noqa: E402
    PermissionFilteredHybridPackageRuntime,
)
from nex_cx.ingestion import ContentIngestionStore  # noqa: E402
from nex_cx.repository import (  # noqa: E402
    build_retrieval_package_persistence_record,
)
from nex_cx.retrieval import register_retrieval_routes  # noqa: E402


SCHEMA_VERSION = "cx_hybrid_retrieval_package_contract.v1"
QUERY = "PRIVATE_S95_QUERY"
EVIDENCE = "PRIVATE_S95_EVIDENCE"
DOCUMENT_ID = "s95-owner-document"
CHUNK_ID = "s95-owner-chunk"


class _CandidateProvider:
    def build_candidate_set(self, **_kwargs: Any) -> dict[str, Any]:
        return deepcopy(_candidate_set())


class _EvidenceMaterializer:
    def load_authorized_texts(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                **ref,
                "chunk_text": EVIDENCE,
                "text_sha256": _digest(EVIDENCE),
            }
            for ref in kwargs["chunk_refs"]
        ]

    def load_authorized_evidence(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                **ref,
                "chunk_policy_id": "chunk_1000_100",
                "chunk_text": EVIDENCE,
                "text_sha256": _digest(EVIDENCE),
                "start_offset": 0,
                "end_offset": len(EVIDENCE),
                "matched_terms": ["private"],
            }
            for ref in kwargs["chunk_refs"]
        ]


def run_cx_hybrid_retrieval_package_contract() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    runtime = PermissionFilteredHybridPackageRuntime(
        candidate_provider=_CandidateProvider(),
        evidence_materializer=_EvidenceMaterializer(),
        now_factory=lambda: "2026-09-22T09:47:00+00:00",
    )
    register_retrieval_routes(app, store=store, hybrid_runtime=runtime)
    client = TestClient(app)

    response = client.post(
        "/api/v1/retrieval/context",
        json={
            "query_text": QUERY,
            "document_scope": {"document_ids": [DOCUMENT_ID]},
            "top_k": 1,
            "purpose": "grounded_answer",
        },
        headers=_headers(),
    )
    package = response.json()
    package_id = package.get("retrieval_package_id", "missing")
    loaded_response = client.get(
        f"/api/v1/retrieval/context/{package_id}",
        headers=_headers(),
    )
    loaded = loaded_response.json()
    persistence = build_retrieval_package_persistence_record(package)
    serialized_persistence = json.dumps(persistence, sort_keys=True)

    checks = {
        "canonical_api_accepted": response.status_code == 200,
        "hardened_runtime_selected": (
            package.get("retrieval_runtime_schema_version")
            == "cx_hybrid_retrieval_runtime.v1"
        ),
        "owner_lineage_attached": (
            package.get("tenant_ref_id") == "s95-tenant"
            and package.get("owner_subject_ref_id") == "s95-owner"
        ),
        "permission_snapshot_attached": (
            package.get("permission_snapshot", {}).get("actor_id") == "s95-owner"
            and package.get("permission_snapshot", {})
            .get("scope_applied", {})
            .get("document_ids")
            == [DOCUMENT_ID]
        ),
        "authorized_evidence_materialized": (
            len(package.get("evidence_items", [])) == 1
            and package["evidence_items"][0].get("chunk_id") == CHUNK_ID
        ),
        "package_saved_and_readable": (
            loaded_response.status_code == 200
            and loaded.get("package_hash") == package.get("package_hash")
        ),
        "persistence_hashes_present": (
            persistence.get("query_text_sha256") == _digest(QUERY)
            and persistence.get("evidence_items", [])[0].get(
                "evidence_text_sha256"
            )
            == _digest(EVIDENCE)
        ),
        "persistence_previews_redacted": (
            persistence.get("query_text_preview") is None
            and persistence.get("evidence_items", [])[0].get(
                "evidence_text_preview"
            )
            is None
        ),
        "private_payload_not_persisted": (
            QUERY not in serialized_persistence
            and EVIDENCE not in serialized_persistence
        ),
        "deterministic_identity": (
            package.get("retrieval_package_id")
            == runtime.build_package(
                {
                    "query_text": QUERY,
                    "document_scope": {"document_ids": [DOCUMENT_ID]},
                    "top_k": 1,
                    "purpose": "grounded_answer",
                },
                access_context=_access_context(),
            ).get("retrieval_package_id")
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "contract_schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "failed_checks": failed,
        "package_schema_version": package.get(
            "retrieval_package_schema_version"
        ),
        "persistence_payload_policy": package.get("persistence_payload_policy"),
        "postgres_required": False,
        "remote_provider_required": False,
    }


def _candidate_set() -> dict[str, Any]:
    permission_snapshot = {
        "permission_snapshot_schema_version": (
            "cx_retrieval_permission_snapshot.v1"
        ),
        "actor_type": "oa.user",
        "actor_id": "s95-owner",
        "tenant_ref": {"type": "oa.tenant", "id": "s95-tenant"},
        "scope_applied": {
            "type": "document_ids",
            "document_ids": [DOCUMENT_ID],
        },
        "visible_document_count": 1,
        "policy_version": "cx.private_owner_active.v1",
    }
    return {
        "hybrid_candidate_set_schema_version": "cx_hybrid_candidate_set.v1",
        "permission_policy": "cx.private_owner_active.v1",
        "permission_enforced_before_candidates": True,
        "query_sha256": _digest(QUERY),
        "query_vector_sha256": "e" * 64,
        "tokenizer_profile": {
            "bm25_tokenizer": "mecab_ko",
            "fallback_used": False,
        },
        "permission_snapshot": permission_snapshot,
        "lexical_candidates": {
            "candidate_source": "postgresql_bm25",
            "candidate_count": 1,
            "candidates": [
                {
                    "lexical_candidate_schema_version": "cx_lexical_candidate.v1",
                    "candidate_source": "postgresql_bm25",
                    "content_object_id": DOCUMENT_ID,
                    "chunk_id": CHUNK_ID,
                    "text_sha256": _digest(EVIDENCE),
                    "bm25_score": 2.0,
                }
            ],
        },
        "vector_candidates": {
            "candidate_source": "postgresql_pgvector",
            "status": "READY",
            "query_dimension": 2,
            "candidate_count": 1,
            "candidates": [
                {
                    "vector_candidate_schema_version": "cx_vector_candidate.v1",
                    "candidate_source": "postgresql_pgvector",
                    "content_object_id": DOCUMENT_ID,
                    "chunk_id": CHUNK_ID,
                    "vector_score": 0.9,
                }
            ],
        },
    }


def _access_context() -> Any:
    from nex_cx.access_context import CxAccessContext

    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="s95-tenant",
        subject_id="s95-owner",
        request_id="s95-0947-request",
        trace_id="94700000000000000000000000000001",
        scopes=("service:call",),
    )


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": "s95-tenant",
        "X-NEX-Subject-ID": "s95-owner",
        "X-Request-ID": "s95-0947-request",
        "traceparent": "00-94700000000000000000000000000001-00f067aa0ba902b7-01",
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def summary_line(result: dict[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "cx_hybrid_retrieval_package_contract="
        f"{str(result.get('status')).lower()} "
        f"checks={result.get('passed_checks', 0)}/{len(checks)} "
        "postgres_required=False remote_required=False"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_hybrid_retrieval_package_contract()
    if args.summary:
        print(summary_line(result))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
