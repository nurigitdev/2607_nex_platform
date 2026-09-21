#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

from fastapi import Request


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_runtime import issue_mock_service_token  # noqa: E402
from nex_cx.authorization import authorize_cx_request  # noqa: E402


SCHEMA_VERSION = "cx_central_authorization_enforcement_evidence.v1"
ROUTE_MODULES = (
    "chunking.py",
    "document_library.py",
    "embedding_index.py",
    "generation.py",
    "ingestion.py",
    "lexical_index.py",
    "processing.py",
    "remediation_execution.py",
    "retrieval.py",
    "summaries.py",
    "summary_embeddings.py",
)


def run_cx_central_authorization_enforcement(
    root: Path = ROOT,
) -> dict[str, Any]:
    cx_root = root / "services" / "nex-cx" / "nex_cx"
    route_evidence = []
    for filename in ROUTE_MODULES:
        path = cx_root / filename
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        route_evidence.append(
            {
                "path": str(path.relative_to(root)) if path.is_file() else filename,
                "present": path.is_file(),
                "central_import": (
                    "from nex_cx.authorization import authorize_cx_request"
                    in content
                ),
                "local_helper_absent": (
                    path.is_file() and "def _authorize_cx_request(" not in content
                ),
                "guard_call_present": "authorize_cx_request(" in content,
            }
        )

    now = datetime.now(UTC)
    allowed_token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        issued_at=now,
    )
    allowed_request = _request("/api/v1/documents")
    allowed_problem = authorize_cx_request(
        allowed_request,
        f"Bearer {allowed_token.access_token}",
        now=now,
    )
    forbidden_token = issue_mock_service_token(
        service_id="nex-mo",
        audience="nex-cx",
        issued_at=now,
    )
    forbidden_problem = authorize_cx_request(
        _request("/api/v1/documents"),
        f"Bearer {forbidden_token.access_token}",
        now=now,
    )
    request_state = vars(allowed_request.state)
    forbidden_payload = (
        json.loads(forbidden_problem.body) if forbidden_problem is not None else {}
    )
    checks = {
        "all_route_modules_use_central_guard": all(
            item["central_import"] and item["guard_call_present"]
            for item in route_evidence
        ),
        "local_auth_helpers_removed": all(
            item["local_helper_absent"] for item in route_evidence
        ),
        "trusted_service_allowed": allowed_problem is None,
        "safe_caller_state_attached": request_state
        == {
            "_state": {
                "cx_caller_service_id": "nex-ae-api",
                "cx_caller_scopes": ("service:call",),
            }
        },
        "bearer_token_not_retained": allowed_token.access_token not in repr(request_state),
        "untrusted_service_forbidden": (
            forbidden_problem is not None
            and forbidden_problem.status_code == 403
            and forbidden_payload.get("error_code") == "CX_CALLER_SERVICE_FORBIDDEN"
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "0913",
        "requirement": "S92",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "cx_central_authorization_failed",
        "checks": checks,
        "route_modules": route_evidence,
        "summary": {
            "route_module_count": len(route_evidence),
            "centralized_route_module_count": sum(
                item["central_import"] and item["local_helper_absent"]
                for item in route_evidence
            ),
            "failed_check_count": sum(not value for value in checks.values()),
            "postgres_required": False,
            "dgx_required": False,
        },
        "next_slice": "0914",
    }


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
        }
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "cx_central_authorization="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"modules={summary.get('centralized_route_module_count', 0)}/"
        f"{summary.get('route_module_count', 0)} "
        f"failed_checks={summary.get('failed_check_count', 0)} "
        f"dgx_required={summary.get('dgx_required')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify centralized CX service authorization enforcement."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_central_authorization_enforcement()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
