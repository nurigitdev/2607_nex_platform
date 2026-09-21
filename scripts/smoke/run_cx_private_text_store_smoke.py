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
    sha256_private_text,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


def _context(subject_id: str = "employee-0915") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0915",
        subject_id=subject_id,
        request_id="request-0915",
        trace_id="91500000000000000000000000000001",
        scopes=("service:call",),
    )


def run_private_text_store_smoke(storage_root: str | Path) -> dict[str, Any]:
    root = Path(storage_root)
    context = _context()
    key = build_private_payload_key(
        context,
        payload_kind="summary_text",
        content_id="summary-0915",
    )
    text = "Confidential restart-safe summary"
    checksum = sha256_private_text(text)
    store = FileSystemCxPrivateTextStore(root)
    receipt = store.put_text(
        access_context=context,
        key=key,
        text=text,
        expected_sha256=checksum,
    )
    first_read = store.get_text(
        access_context=context,
        key=key,
        expected_sha256=checksum,
    )
    repeated = store.put_text(
        access_context=context,
        key=key,
        text=text,
        expected_sha256=checksum,
    )
    restarted = FileSystemCxPrivateTextStore(root)
    restart_read = restarted.get_text(
        access_context=context,
        key=key,
        expected_sha256=checksum,
    )

    cross_owner_hidden = False
    try:
        restarted.get_text(
            access_context=_context("employee-other"),
            key=key,
            expected_sha256=checksum,
        )
    except CxPrivateContentError as exc:
        cross_owner_hidden = exc.status_code == 404

    immutable_conflict = False
    try:
        restarted.put_text(
            access_context=context,
            key=key,
            text="replacement",
            expected_sha256=sha256_private_text("replacement"),
        )
    except CxPrivateContentError as exc:
        immutable_conflict = exc.error_code == "CX_PRIVATE_TEXT_IMMUTABLE_CONFLICT"

    uri_redacted = all(
        value not in receipt.storage_uri
        for value in (context.tenant_id, context.subject_id, key.content_id)
    )
    deleted = restarted.delete_text(access_context=context, key=key)
    missing_after_delete = (
        restarted.get_text(
            access_context=context,
            key=key,
            expected_sha256=checksum,
        )
        is None
    )
    checks = (
        first_read == text,
        repeated == receipt,
        restart_read == text,
        uri_redacted,
        cross_owner_hidden,
        immutable_conflict,
        deleted,
        missing_after_delete,
    )
    return {
        "status": "PASS" if all(checks) else "FAIL",
        "checks": sum(checks),
        "checks_total": len(checks),
        "storage_backend": receipt.storage_backend,
        "owner_scoped": cross_owner_hidden,
        "restart_reload": restart_read == text,
        "immutable": immutable_conflict,
        "uri_redacted": uri_redacted,
        "dgx_required": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--storage-root")
    args = parser.parse_args()

    if args.storage_root:
        result = run_private_text_store_smoke(args.storage_root)
    else:
        with tempfile.TemporaryDirectory(prefix="nex-cx-private-text-") as temp_dir:
            result = run_private_text_store_smoke(temp_dir)

    if args.summary:
        print(
            "cx_private_text_store="
            f"{result['status'].lower()} "
            f"checks={result['checks']}/{result['checks_total']} "
            f"restart_reload={result['restart_reload']} "
            f"owner_scoped={result['owner_scoped']} "
            f"dgx_required={result['dgx_required']}"
        )
    else:
        print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
