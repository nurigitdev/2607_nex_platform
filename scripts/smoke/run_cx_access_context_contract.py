#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_runtime import issue_mock_service_token
from nex_cx.access_context import (
    build_access_context_ownership_ref,
    ownership_ref_matches_access_context,
    resolve_cx_access_context,
)
from nex_cx.source_ownership import ownership_ref_has_private_identity_payload


SCHEMA_VERSION = "cx_access_context_contract_evidence.v1"


def run_cx_access_context_contract() -> dict[str, Any]:
    now = datetime.now(UTC)
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        issued_at=now,
    )
    context = resolve_cx_access_context(
        authorization=f"Bearer {issued.access_token}",
        tenant_id="tenant-s92",
        subject_id="employee-9201",
        request_id="request-s92-0912",
        trace_id="91200000000000000000000000000001",
        now=now,
    )
    wire = context.to_wire()
    ownership_ref = build_access_context_ownership_ref(context)
    checks = {
        "trusted_caller_resolved": context.caller_service_id == "nex-ae-api",
        "owner_scope_resolved": context.ownership_key
        == ("tenant-s92", "employee-9201"),
        "ownership_ref_matches": ownership_ref_matches_access_context(
            context, ownership_ref
        ),
        "context_omits_bearer_token": issued.access_token not in repr(wire),
        "ownership_ref_omits_private_identity": (
            not ownership_ref_has_private_identity_payload(ownership_ref)
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "0912",
        "requirement": "S92",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "cx_access_context_contract_failed",
        "context": wire,
        "ownership_ref": ownership_ref,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "dgx_required": False,
            "postgres_required": False,
        },
        "next_slice": "0913",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "cx_access_context_contract="
        f"{evidence.get('status')} "
        f"checks={summary.get('passed_check_count')}/{summary.get('check_count')} "
        f"postgres_required={summary.get('postgres_required')} "
        f"dgx_required={summary.get('dgx_required')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic CX access-context contract evidence."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_access_context_contract()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
