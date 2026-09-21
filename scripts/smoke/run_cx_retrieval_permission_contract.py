#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
SHARED_PATH = ROOT / "services" / "_shared"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.retrieval_permissions import (  # noqa: E402
    PERMISSION_POLICY_ID,
    RetrievalPermissionError,
    build_evidence_permission_result,
    build_permission_snapshot,
    evaluate_retrieval_permission,
    filter_retrieval_document_scope,
)


SCHEMA_VERSION = "cx_retrieval_permission_contract_evidence.v1"


def run_cx_retrieval_permission_contract() -> dict[str, Any]:
    owner = _context("tenant-a", "owner-a")
    active = _content("tenant-a", "owner-a", "ACTIVE")
    inactive = _content("tenant-a", "owner-a", "DELETED")
    foreign = _content("tenant-a", "owner-b", "ACTIVE")
    allowed = evaluate_retrieval_permission(owner, active)
    result = filter_retrieval_document_scope(
        access_context=owner,
        requested_document_ids=["doc-a", "doc-a"],
        content_objects={"doc-a": active},
    )
    snapshot = build_permission_snapshot(
        access_context=owner,
        scope_type="explicit_document_ids",
        filter_result=result,
    )
    checks = {
        "active_owner_visible": allowed["visible"] is True,
        "foreign_owner_hidden": evaluate_retrieval_permission(owner, foreign)
        == evaluate_retrieval_permission(owner, None),
        "inactive_owner_hidden": evaluate_retrieval_permission(owner, inactive)
        == evaluate_retrieval_permission(owner, None),
        "explicit_scope_deduplicated": result["visible_document_ids"] == ["doc-a"],
        "snapshot_uses_authenticated_subject": (
            snapshot["actor_id"] == "owner-a"
            and snapshot["tenant_ref"]["id"] == "tenant-a"
        ),
        "filter_counts_measured": (
            snapshot["visible_document_count"] == 1
            and snapshot["filtered_document_count"] == 0
            and snapshot["filtered_chunk_count"] == 0
        ),
        "evidence_policy_bound": (
            build_evidence_permission_result(allowed)["policy_version"]
            == PERMISSION_POLICY_ID
        ),
        "mixed_scope_fails_closed": _mixed_scope_fails_closed(owner, active, foreign),
    }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "0942",
        "requirement": "S95",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "policy_id": PERMISSION_POLICY_ID,
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "postgres_required": False,
        "remote_provider_required": False,
        "next_slice": "0943",
    }


def _context(tenant_id: str, subject_id: str) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="s95-permission-contract",
        trace_id="94200000000000000000000000000001",
        scopes=("service:call",),
    )


def _content(tenant_id: str, subject_id: str, status: str) -> dict[str, Any]:
    return {
        "lifecycle_status": status,
        "ownership_ref": {
            "ownership_schema_version": "cx_source_ownership_ref.v1",
            "tenant_ref": {"type": "oa.tenant", "id": tenant_id},
            "owner_subject_ref": {"type": "oa.user", "id": subject_id},
            "uploaded_by_subject_ref": {"type": "oa.user", "id": subject_id},
            "legacy": {
                "tenant_id": tenant_id,
                "owner_user_id": subject_id,
                "uploaded_by_user_id": subject_id,
            },
        },
    }


def _mixed_scope_fails_closed(
    context: CxAccessContext,
    active: Mapping[str, Any],
    foreign: Mapping[str, Any],
) -> bool:
    try:
        filter_retrieval_document_scope(
            access_context=context,
            requested_document_ids=["doc-a", "doc-b"],
            content_objects={"doc-a": active, "doc-b": foreign},
        )
    except RetrievalPermissionError as exc:
        return exc.status_code == 404 and exc.error_code == "cx.document_scope_not_found"
    return False


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "cx_retrieval_permission_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in (result.get('checks') or {}).values())}/"
        f"{result.get('check_count', 0)} "
        f"policy={result.get('policy_id', 'unknown')} "
        f"postgres_required={result.get('postgres_required', True)} "
        f"remote_required={result.get('remote_provider_required', True)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_retrieval_permission_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
