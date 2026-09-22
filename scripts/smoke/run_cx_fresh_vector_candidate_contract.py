#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any
from uuid import NAMESPACE_URL, uuid5


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.vector_candidates import collect_fresh_vector_candidates  # noqa: E402
from nex_cx.vector_index_freshness import (  # noqa: E402
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    build_vector_payload_snapshot,
    mark_vector_index_ready,
)
from nex_cx.vector_index_repository import (  # noqa: E402
    InMemoryVectorIndexRepository,
)


SCHEMA_VERSION = "cx_fresh_vector_candidate_contract.v1"


class _BoundVectorStore:
    def __init__(
        self,
        snapshot: dict[str, Any],
        matches: list[dict[str, Any]],
    ) -> None:
        self._snapshot = snapshot
        self._matches = matches

    def payload_snapshot(self, *, access_context: CxAccessContext) -> dict[str, Any]:
        return deepcopy(self._snapshot)

    def search(
        self,
        *,
        access_context: CxAccessContext,
        query_vector: tuple[float, ...],
        limit: int,
    ) -> list[dict[str, Any]]:
        return deepcopy(self._matches[:limit])


class _VectorStore:
    def __init__(self, bounds: dict[str, _BoundVectorStore]) -> None:
        self._bounds = bounds

    def bind_index(self, manifest: dict[str, Any]) -> _BoundVectorStore:
        return self._bounds[manifest["vector_index_id"]]


def run_cx_fresh_vector_candidate_contract() -> dict[str, Any]:
    context = CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="s95-tenant",
        subject_id="s95-owner",
        request_id="s95-vector-candidate-request",
        trace_id="94400000000000000000000000000001",
        scopes=("service:call",),
    )
    fixtures = [
        _fixture("fresh", owner="s95-owner", status="READY", score=0.91),
        _fixture("building", owner="s95-owner", status="BUILDING", score=0.8),
        _fixture("foreign", owner="other-owner", status="READY", score=0.99),
    ]
    repository = InMemoryVectorIndexRepository()
    bounds: dict[str, _BoundVectorStore] = {}
    targets: list[dict[str, Any]] = []
    for fixture in fixtures:
        repository.create(fixture["manifest"])
        bounds[fixture["manifest"]["vector_index_id"]] = _BoundVectorStore(
            fixture["payload_snapshot"],
            fixture["matches"],
        )
        targets.append(fixture["target"])

    first = collect_fresh_vector_candidates(
        access_context=context,
        targets=targets,
        query_vector=(1.0, 0.0),
        limit=5,
        repository=repository,
        vector_store=_VectorStore(bounds),
    )
    second = collect_fresh_vector_candidates(
        access_context=context,
        targets=targets,
        query_vector=(1.0, 0.0),
        limit=5,
        repository=repository,
        vector_store=_VectorStore(bounds),
    )
    candidate = first["candidates"][0] if first["candidates"] else {}
    private_fields = {"embedding", "vector", "chunk_text", "source_text"}
    excluded_ids = {
        fixtures[1]["manifest"]["vector_index_id"],
        fixtures[2]["manifest"]["vector_index_id"],
    }
    checks = {
        "schema_current": (
            first["vector_candidate_result_schema_version"]
            == "cx_vector_candidate_result.v1"
        ),
        "fresh_index_admitted": first["admitted_index_count"] == 1,
        "unready_index_excluded": (
            first["exclusion_counts"].get("INDEX_NOT_READY") == 1
        ),
        "owner_hidden_index_excluded": (
            first["exclusion_counts"].get("INDEX_NOT_FOUND") == 1
        ),
        "fresh_candidate_returned": (
            first["candidate_count"] == 1
            and candidate.get("chunk_id") == fixtures[0]["chunk_id"]
        ),
        "candidate_metadata_only": private_fields.isdisjoint(candidate),
        "excluded_identity_not_disclosed": excluded_ids.isdisjoint(
            set(_all_strings(first))
        ),
        "deterministic_result": first == second,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "contract_schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "failed_checks": failed,
        "permission_policy": "cx.private_owner_active.v1",
        "postgres_required": False,
        "remote_provider_required": False,
        "result_summary": {
            "requested_index_count": first["requested_index_count"],
            "admitted_index_count": first["admitted_index_count"],
            "excluded_index_count": first["excluded_index_count"],
            "candidate_count": first["candidate_count"],
            "exclusion_counts": first["exclusion_counts"],
        },
    }


def _fixture(
    label: str,
    *,
    owner: str,
    status: str,
    score: float,
) -> dict[str, Any]:
    chunk_id = str(uuid5(NAMESPACE_URL, f"s95:{label}:chunk"))
    source = build_source_snapshot(
        chunk_set_id=str(uuid5(NAMESPACE_URL, f"s95:{label}:chunk-set")),
        chunk_policy_id="1000_100",
        source_markdown_sha256=_hex(label, "source"),
        chunks=[
            {
                "chunk_id": chunk_id,
                "ordinal": 0,
                "text_sha256": _hex(label, "chunk"),
            }
        ],
    )
    profile = build_embedding_profile(
        provider_alias="mock-s95",
        model_profile_id="Qwen3-Embedding-4B",
        model_revision="bf16",
        deployment_id="contract-local",
        vector_dimension=2,
    )
    manifest = build_vector_index_manifest(
        content_object_id=str(uuid5(NAMESPACE_URL, f"s95:{label}:content")),
        tenant_ref={"type": "oa.tenant", "id": "s95-tenant"},
        owner_subject_ref={"type": "oa.user", "id": owner},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id=f"s95-{label}-trace",
        request_id=f"s95-{label}-request",
        observed_at="2026-09-22T02:00:00Z",
    )
    receipt = {
        "chunk_id": chunk_id,
        "embedding_sha256": _hex(label, "embedding"),
        "vector_dimension": 2,
        "storage_uri": f"cx-private://pgvector/{manifest['vector_index_id']}/{chunk_id}",
    }
    if status == "READY":
        manifest = mark_vector_index_ready(
            manifest,
            payload_receipts=[receipt],
            observed_at="2026-09-22T02:01:00Z",
        )
    return {
        "chunk_id": chunk_id,
        "manifest": manifest,
        "payload_snapshot": build_vector_payload_snapshot([receipt]),
        "matches": [
            {"chunk_id": chunk_id, "score": score, "distance": 1.0 - score}
        ],
        "target": {
            "vector_index_id": manifest["vector_index_id"],
            "content_object_id": manifest["content_object_id"],
            "source_snapshot": source,
            "embedding_profile": profile,
            "permission_decision": {
                "visible": True,
                "policy_version": "cx.private_owner_active.v1",
            },
        },
    }


def _hex(*parts: str) -> str:
    import hashlib

    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def _all_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            strings.extend((str(key), *_all_strings(item)))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_all_strings(item))
        return strings
    return []


def summary_line(result: dict[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        f"cx_fresh_vector_candidate_contract={str(result.get('status')).lower()} "
        f"checks={result.get('passed_checks', 0)}/{len(checks)} "
        "policy=cx.private_owner_active.v1 postgres_required=False "
        "remote_required=False"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_fresh_vector_candidate_contract()
    if args.summary:
        print(summary_line(result))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
