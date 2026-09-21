#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

from fastapi import Request


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-ae-api", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_ae_api.cx_owner_context import cx_owner_headers  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402
from nex_cx.api_ownership import (  # noqa: E402
    CxApiOwnershipError,
    owner_scoped_record,
    record_visible_to_owner,
    require_optional_owner_aliases_match,
)
from nex_cx.authorization import authorize_cx_owner_request  # noqa: E402
from nex_cx.contract_api_drift_audit import (  # noqa: E402
    build_cx_contract_api_drift_audit,
)


SCHEMA_VERSION = "cx_api_contract_ownership_hardening.v1"
ROUTE_MODULES = (
    "chunking.py",
    "document_library.py",
    "embedding_index.py",
    "generation.py",
    "ingestion.py",
    "ingestion_operations.py",
    "lexical_index.py",
    "processing.py",
    "remediation_execution.py",
    "retrieval.py",
    "summaries.py",
    "summary_embeddings.py",
)
REQUIRED_PATHS = (
    Path("services/nex-cx/nex_cx/api_ownership.py"),
    Path("services/nex-ae-api/nex_ae_api/cx_owner_context.py"),
    Path("contracts/openapi/nex-cx.openapi.yaml"),
    Path(
        "contracts/tests/negative/retrieval/"
        "cx_source_ownership_boundary_decision.missing_status.json"
    ),
    Path("docs/slices/0918_cx_api_contract_ownership_hardening.md"),
    Path("scripts/quality/run_quality_gate.sh"),
)


def run_cx_api_contract_ownership_hardening(root: Path = ROOT) -> dict[str, Any]:
    required_paths = [
        {"path": str(path), "present": (root / path).is_file()}
        for path in REQUIRED_PATHS
    ]
    cx_root = root / "services/nex-cx/nex_cx"
    route_evidence = []
    for filename in ROUTE_MODULES:
        source = _read_text(cx_root / filename)
        route_evidence.append(
            {
                "module": filename,
                "owner_guard_present": "authorize_cx_owner_request(" in source,
                "central_guard_imported": (
                    "from nex_cx.authorization import" in source
                ),
            }
        )

    openapi = _read_text(root / "contracts/openapi/nex-cx.openapi.yaml")
    negative_index = _read_text(root / "contracts/tests/negative/index.json")
    quality_gate = _read_text(root / "scripts/quality/run_quality_gate.sh")
    runtime = _runtime_evidence()
    drift = build_cx_contract_api_drift_audit(root)
    checks = {
        "required_paths_present": all(item["present"] for item in required_paths),
        "all_private_routes_use_owner_guard": all(
            item["owner_guard_present"] and item["central_guard_imported"]
            for item in route_evidence
        ),
        "canonical_headers_documented": all(
            token in openapi
            for token in ("X-NEX-Tenant-ID", "X-NEX-Subject-ID")
        ),
        "owner_context_applies_to_runtime_paths": (
            openapi.count("parameters: *cxOwnerContextParameters") >= 27
        ),
        "openapi_version_hardened": "version: 0.94.0" in openapi,
        "negative_fixture_indexed": (
            "cx_source_ownership_boundary_decision.missing_status.json"
            in negative_index
        ),
        "runtime_owner_context_resolved": runtime["owner_context_resolved"],
        "runtime_cross_owner_hidden": runtime["cross_owner_hidden"],
        "ae_owner_headers_propagated": runtime["ae_owner_headers_propagated"],
        "contract_api_drift_zero": (
            drift.get("status") == "PASS"
            and drift.get("summary", {}).get("drift_count") == 0
        ),
        "quality_gate_hook_present": (
            "run_cx_api_contract_ownership_hardening.py" in quality_gate
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "0918",
        "requirement": "S92",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": None if not issues else "cx_api_ownership_hardening_failed",
        "decision": {
            "owner_transport": ["X-NEX-Tenant-ID", "X-NEX-Subject-ID"],
            "cross_owner_visibility": "not-found",
            "owner_alias_policy": "must-match-authenticated-context",
            "postgres_smoke_slice": "0919",
            "dgx_live_provider_required": False,
        },
        "summary": {
            "route_module_count": len(route_evidence),
            "owner_guarded_module_count": sum(
                item["owner_guard_present"] for item in route_evidence
            ),
            "runtime_operation_count": drift.get("summary", {}).get(
                "runtime_operation_count", 0
            ),
            "drift_count": drift.get("summary", {}).get("drift_count", 0),
            "check_count": len(checks),
            "issue_count": len(issues),
        },
        "checks": checks,
        "runtime": runtime,
        "required_paths": required_paths,
        "route_modules": route_evidence,
        "issues": issues,
        "next_slice": "0919",
    }


def _runtime_evidence() -> dict[str, bool]:
    now = datetime.now(UTC)
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        issued_at=now,
    )
    context = authorize_cx_owner_request(
        _request(),
        f"Bearer {issued.access_token}",
        tenant_id="tenant-s92",
        subject_id="employee-0918",
        now=now,
    )
    if not hasattr(context, "ownership_key"):
        return {
            "owner_context_resolved": False,
            "cross_owner_hidden": False,
            "ae_owner_headers_propagated": False,
        }
    owned = owner_scoped_record(context, {"document_id": "doc-0918"})
    try:
        require_optional_owner_aliases_match(
            context,
            tenant_id="tenant-s92",
            owner_user_id="other-user",
        )
    except CxApiOwnershipError as exc:
        mismatch_rejected = exc.error_code == "cx.owner_scope_mismatch"
    else:
        mismatch_rejected = False
    headers = cx_owner_headers("tenant-s92", "employee-0918")
    return {
        "owner_context_resolved": context.ownership_key
        == ("tenant-s92", "employee-0918"),
        "cross_owner_hidden": mismatch_rejected
        and not record_visible_to_owner(
            type(context)(
                caller_service_id=context.caller_service_id,
                tenant_id=context.tenant_id,
                subject_id="other-user",
                request_id=context.request_id,
                trace_id=context.trace_id,
                scopes=context.scopes,
            ),
            owned,
        ),
        "ae_owner_headers_propagated": headers
        == {
            "X-NEX-Tenant-ID": "tenant-s92",
            "X-NEX-Subject-ID": "employee-0918",
        },
    }


def _request() -> Request:
    trace_id = "91800000000000000000000000000001"
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents/doc-0918",
            "raw_path": b"/api/v1/documents/doc-0918",
            "query_string": b"",
            "headers": [
                (b"x-request-id", b"request-0918"),
                (
                    b"traceparent",
                    f"00-{trace_id}-00f067aa0ba902b7-01".encode(),
                ),
            ],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
        }
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    decision = evidence.get("decision") or {}
    return (
        "cx_api_contract_ownership_hardening="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"modules={summary.get('owner_guarded_module_count', 0)}/"
        f"{summary.get('route_module_count', 0)} "
        f"drift={summary.get('drift_count', 0)} "
        f"dgx_required={decision.get('dgx_live_provider_required', False)} "
        f"issues={summary.get('issue_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_api_contract_ownership_hardening()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
