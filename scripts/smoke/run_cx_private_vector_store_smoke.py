from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Any

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CxPrivateContentError,
    build_private_payload_key,
    sha256_private_vector,
)
from nex_cx.private_vector_store import (
    FileSystemCxVectorStore,
    persist_and_link_private_vector,
)


def _context(subject_id: str = "employee-0916") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0916",
        subject_id=subject_id,
        request_id="request-0916",
        trace_id="91600000000000000000000000000001",
        scopes=("service:call",),
    )


def run_private_vector_store_smoke(storage_root: str | Path) -> dict[str, Any]:
    root = Path(storage_root)
    context = _context()
    vector = (0.125, -0.25, 0.5)
    checksum = sha256_private_vector(vector)
    store = FileSystemCxVectorStore(root)
    linked = persist_and_link_private_vector(
        access_context=context,
        vector_store=store,
        payload_kind="chunk_embedding",
        content_id="chunk-0916",
        vector=vector,
        metadata={
            "chunk_id": "chunk-0916",
            "embedding_sha256": checksum,
            "vector_dimension": len(vector),
        },
    )
    key = build_private_payload_key(
        context,
        payload_kind="chunk_embedding",
        content_id="chunk-0916",
    )
    first_read = store.get_vector(
        access_context=context,
        key=key,
        expected_sha256=checksum,
        expected_dimension=len(vector),
    )
    restarted = FileSystemCxVectorStore(root)
    restart_read = restarted.get_vector(
        access_context=context,
        key=key,
        expected_sha256=checksum,
        expected_dimension=len(vector),
    )

    cross_owner_hidden = False
    try:
        restarted.get_vector(
            access_context=_context("employee-other"),
            key=key,
            expected_sha256=checksum,
            expected_dimension=len(vector),
        )
    except CxPrivateContentError as exc:
        cross_owner_hidden = exc.status_code == 404

    immutable_conflict = False
    try:
        persist_and_link_private_vector(
            access_context=context,
            vector_store=restarted,
            payload_kind="chunk_embedding",
            content_id="chunk-0916",
            vector=(1.0, 2.0, 3.0),
            metadata={
                "chunk_id": "chunk-0916",
                "embedding_sha256": sha256_private_vector((1.0, 2.0, 3.0)),
                "vector_dimension": 3,
            },
        )
    except CxPrivateContentError as exc:
        immutable_conflict = exc.error_code == "CX_PRIVATE_VECTOR_IMMUTABLE_CONFLICT"

    uri = linked.get("embedding_storage_uri")
    uri_redacted = isinstance(uri, str) and all(
        value not in uri
        for value in (context.tenant_id, context.subject_id, key.content_id)
    )
    metadata_only = "embedding" not in linked and "vector" not in linked
    deleted = restarted.delete_vector(access_context=context, key=key)
    missing_after_delete = (
        restarted.get_vector(
            access_context=context,
            key=key,
            expected_sha256=checksum,
            expected_dimension=len(vector),
        )
        is None
    )
    checks = (
        first_read == vector,
        restart_read == vector,
        linked["embedding_sha256"] == checksum,
        linked["vector_dimension"] == len(vector),
        uri_redacted,
        metadata_only,
        cross_owner_hidden,
        immutable_conflict,
        deleted,
        missing_after_delete,
    )
    return {
        "status": "PASS" if all(checks) else "FAIL",
        "checks": sum(checks),
        "checks_total": len(checks),
        "storage_backend": "filesystem-vector-v1",
        "owner_scoped": cross_owner_hidden,
        "restart_reload": restart_read == vector,
        "metadata_linked": linked["embedding_sha256"] == checksum,
        "immutable": immutable_conflict,
        "dgx_required": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--storage-root")
    args = parser.parse_args()

    if args.storage_root:
        result = run_private_vector_store_smoke(args.storage_root)
    else:
        with tempfile.TemporaryDirectory(prefix="nex-cx-private-vector-") as temp_dir:
            result = run_private_vector_store_smoke(temp_dir)

    if args.summary:
        print(
            "cx_private_vector_store="
            f"{result['status'].lower()} "
            f"checks={result['checks']}/{result['checks_total']} "
            f"restart_reload={result['restart_reload']} "
            f"metadata_linked={result['metadata_linked']} "
            f"dgx_required={result['dgx_required']}"
        )
    else:
        print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
