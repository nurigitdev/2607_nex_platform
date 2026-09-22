#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
SHARED_PATH = ROOT / "services" / "_shared"
for path in (CX_PATH, SHARED_PATH):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.document_summary_storage import (  # noqa: E402
    load_document_summary_text,
    persist_document_summary_text,
)
from nex_cx.private_text_store import FileSystemCxPrivateTextStore  # noqa: E402
from nex_cx.private_content import sha256_private_text  # noqa: E402


SCHEMA_VERSION = "cx_document_summary_storage_evidence.v1"


def _context(subject_id: str = "employee-0953") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0953",
        subject_id=subject_id,
        request_id="request-0953",
        trace_id="95300000000000000000000000000001",
        scopes=("service:call",),
    )


def run_cx_document_summary_storage_smoke(storage_root: str | Path) -> dict[str, Any]:
    text = "Private summary payload for restart evidence"
    metadata = {
        "document_summary_id": "summary-0953",
        "document_id": "document-0953",
        "summary_text_sha256": sha256_private_text(text),
        "summary_storage_uri": "memory://cx/document-summaries/summary-0953.md",
    }
    first_store = FileSystemCxPrivateTextStore(storage_root)
    stored = persist_document_summary_text(
        private_text_store=first_store,
        access_context=_context(),
        summary=metadata,
        summary_text=text,
    )
    restarted_store = FileSystemCxPrivateTextStore(storage_root)
    reloaded = load_document_summary_text(
        private_text_store=restarted_store,
        access_context=_context(),
        summary=stored,
    )
    cross_owner = load_document_summary_text(
        private_text_store=restarted_store,
        access_context=_context("employee-other"),
        summary=stored,
    )
    serialized = json.dumps(stored, sort_keys=True)
    checks = {
        "durable_uri": str(stored["summary_storage_uri"]).startswith("cx-private://"),
        "restart_reload": reloaded == text,
        "hash_bound": stored["summary_text_sha256"] == sha256_private_text(text),
        "owner_scoped": cross_owner is None,
        "payload_not_in_metadata": text not in serialized,
        "tenant_redacted": _context().tenant_id not in serialized,
        "subject_redacted": _context().subject_id not in serialized,
        "content_id_redacted_from_uri": (
            metadata["document_summary_id"] not in str(stored["summary_storage_uri"])
        ),
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "checks_total": len(checks),
        "storage_backend": "filesystem-text-v1",
        "restart_reload": checks["restart_reload"],
        "owner_scoped": checks["owner_scoped"],
        "postgres_required": False,
        "remote_provider_required": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "cx_document_summary_storage="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={result.get('passed_checks', 0)}/{result.get('checks_total', 0)} "
        f"restart_reload={result.get('restart_reload', False)} "
        f"postgres_required={result.get('postgres_required', True)} "
        f"remote_required={result.get('remote_provider_required', True)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--storage-root")
    args = parser.parse_args(argv)
    if args.storage_root:
        result = run_cx_document_summary_storage_smoke(args.storage_root)
    else:
        with tempfile.TemporaryDirectory(prefix="nex-cx-summary-storage-") as temp_dir:
            result = run_cx_document_summary_storage_smoke(temp_dir)
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
