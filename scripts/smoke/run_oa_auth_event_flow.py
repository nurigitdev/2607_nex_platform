#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_oa.auth_events import InMemoryOaAuthEventRepository  # noqa: E402


def run_oa_auth_event_flow() -> dict[str, Any]:
    repository = InMemoryOaAuthEventRepository()
    repository.record_event(
        {
            "event_type": "LOGIN_SUCCEEDED",
            "outcome": "SUCCEEDED",
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "credential_id": "credential-a",
            "actor_ref": "nex.service:nex-ae-api",
            "request_id": "request-1228",
            "trace_id": "1234567890abcdef1234567890abcdef",
            "details": {"credential_status": "ACTIVE"},
        }
    )
    repository.record_event(
        {
            "event_type": "LOGIN_FAILED",
            "outcome": "BLOCKED",
            "tenant_id": "tenant-a",
            "actor_ref": "nex.service:nex-ae-api",
            "details": {"error_code": "oa.credential_not_verified"},
        }
    )
    events = repository.list_events(tenant_id="tenant-a")
    serialized = json.dumps(events, sort_keys=True).lower()
    checks = {
        "events_persisted": len(events) == 2,
        "reverse_time_projection": events[0]["event_type"] == "LOGIN_FAILED",
        "success_subject_projected": events[1]["subject_ref"]["id"] == "user-a",
        "failed_subject_omitted": events[0]["subject_ref"] is None,
        "password_absent": "password" not in serialized,
        "token_absent": "token" not in serialized,
        "session_id_absent": "session_id" not in serialized,
    }
    return {
        "evidence_schema_version": "oa_auth_event_flow_evidence.v1",
        "slice": "1228",
        "requirement": "S123",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "event_count": len(events),
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        f"oa_auth_event_flow={str(evidence.get('status')).lower()} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"events={summary.get('event_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_auth_event_flow()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
