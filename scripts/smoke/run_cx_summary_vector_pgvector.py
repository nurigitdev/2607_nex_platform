#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.private_content import (  # noqa: E402
    build_private_payload_key,
    sha256_private_vector,
)
from nex_cx.summary_pgvector_store import (  # noqa: E402
    SUMMARY_PGVECTOR_STORAGE_BACKEND,
    SummaryPgVectorStore,
    build_summary_vector_binding,
)


MIGRATION_PATH = (
    ROOT
    / "database"
    / "nex-cx"
    / "migrations"
    / "0955_cx_summary_vector_persistence.sql"
)


class _Result:
    def __init__(self, *, one=None, rowcount=-1):
        self._one = one
        self.rowcount = rowcount

    def mappings(self):
        return self

    def one_or_none(self):
        return self._one


class _Session:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters):
        sql = " ".join(str(statement).split())
        identity = parameters["summary_embedding_id"]
        if sql.startswith("SELECT summary_vector_id"):
            return _Result(one=self.rows.get(identity))
        if sql.startswith("INSERT INTO cx_summary_vectors"):
            self.rows[identity] = {
                **parameters,
                "tenant_ref_id": parameters["tenant_id"],
                "owner_subject_ref_id": parameters["owner_subject_id"],
            }
            return _Result(rowcount=1)
        if sql.startswith("DELETE FROM cx_summary_vectors"):
            return _Result(rowcount=0)
        raise AssertionError(sql)


class _SessionFactory:
    def __init__(self):
        self.rows = {}

    def __call__(self):
        return _Session(self.rows)

    def begin(self):
        return _Session(self.rows)


def run_cx_summary_vector_pgvector() -> dict[str, object]:
    context = CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0955",
        subject_id="owner-0955",
        request_id="request-0955",
        trace_id="09550000000000000000000000000001",
        scopes=("service:call",),
    )
    content_id = str(uuid4())
    summary_id = str(uuid4())
    vector = (1.0, 0.0, 0.0)
    binding = build_summary_vector_binding(
        access_context=context,
        content_object={
            "content_object_id": content_id,
            "lifecycle_status": "ACTIVE",
            "ownership_ref": {
                "tenant_ref": {"type": "oa.tenant", "id": context.tenant_id},
                "owner_subject_ref": {
                    "type": "oa.user",
                    "id": context.subject_id,
                },
            },
        },
        summary={
            "document_summary_id": summary_id,
            "content_object_id": content_id,
            "summary_text_sha256": "a" * 64,
            "status": "READY",
        },
        embedding={
            "summary_embedding_id": str(uuid4()),
            "document_summary_id": summary_id,
            "provider_alias": "qwen-embedding-default",
            "model_profile_id": "Qwen3-Embedding-4B",
            "model_revision": "bf16",
            "deployment_id": "mock-0955",
            "vector_dimension": len(vector),
            "embedding_sha256": sha256_private_vector(vector),
            "status": "READY",
            "created_at": "2026-09-22T12:00:00Z",
        },
    )
    factory = _SessionFactory()
    store = SummaryPgVectorStore(
        factory,  # type: ignore[arg-type]
        redacted_database_url="postgresql://user:***@localhost/test",
        uses_primary_database=True,
    ).bind_summary(binding)
    key = build_private_payload_key(
        context,
        payload_kind="summary_embedding",
        content_id=summary_id,
    )
    receipt = store.put_vector(
        access_context=context,
        key=key,
        vector=vector,
        expected_sha256=binding.embedding_sha256,
    )
    loaded = store.get_vector(
        access_context=context,
        key=key,
        expected_sha256=binding.embedding_sha256,
        expected_dimension=len(vector),
    )
    freshness = store.freshness(access_context=context)
    compact_sql = " ".join(MIGRATION_PATH.read_text(encoding="utf-8").lower().split())
    checks = {
        "table_short": "create table if not exists cx_summary_vectors" in compact_sql,
        "owner_columns": "owner_subject_ref_id text not null" in compact_sql,
        "lineage_trigger": "cx_assert_summary_vector_lineage" in compact_sql,
        "dimension_guard": "vector_dims(embedding) = vector_dimension" in compact_sql,
        "hnsw_2560": "embedding::halfvec(2560)" in compact_sql,
        "backend_pgvector": receipt.storage_backend == SUMMARY_PGVECTOR_STORAGE_BACKEND,
        "private_uri": receipt.storage_uri.startswith("cx-private://pgvector/summary/"),
        "round_trip": loaded == vector,
        "fresh_ready": freshness["usable"] is True,
        "no_provider_needed": True,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "table": "cx_summary_vectors",
        "postgres_required": False,
        "remote_required": False,
    }


def _format_summary(result: dict[str, object]) -> str:
    return (
        f"cx_summary_vector_pgvector={str(result['status']).lower()} "
        f"checks={result['check_count'] - len(result['failed_checks'])}/"
        f"{result['check_count']} table={result['table']} "
        "postgres_required=False remote_required=False"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = run_cx_summary_vector_pgvector()
    print(_format_summary(result) if args.summary else json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
