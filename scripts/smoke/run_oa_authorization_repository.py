#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.authorization_repository import InMemoryOaAuthorizationRepository  # noqa: E402


CONTEXT = {
    "actor_ref": "nex.service:nex-ag",
    "request_id": "request-1235",
    "trace_id": "trace-1235",
}


def run_oa_authorization_repository() -> dict[str, Any]:
    repository = InMemoryOaAuthorizationRepository()
    role = repository.upsert_role(
        {
            "tenant_id": "tenant-a",
            "role_id": "editor",
            "scopes": ["document:read", "document:write"],
            "expected_revision": 0,
        },
        context=CONTEXT,
    )
    group = repository.upsert_group(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "expected_revision": 0,
        },
        context=CONTEXT,
    )
    repository.upsert_group_member(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "subject_id": "user-a",
            "expected_revision": 0,
        },
        context=CONTEXT,
    )
    repository.upsert_group_role(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "role_id": "editor",
            "expected_revision": 0,
        },
        context=CONTEXT,
    )
    snapshot = repository.authorization_inputs(tenant_id="tenant-a", subject_id="user-a")
    events = repository.list_events(tenant_id="tenant-a")
    checks = {
        "role_persisted": role["record"]["revision"] == 1,
        "group_persisted": group["record"]["revision"] == 1,
        "snapshot_complete": {key: len(value) for key, value in snapshot.items()}
        == {"roles": 1, "groups": 1, "group_members": 1, "group_roles": 1},
        "events_append_only": len(events) == 4,
        "events_privacy_safe": not any(
            private in json.dumps(events).lower()
            for private in ("password", "session_id", "service_token", "database_url")
        ),
        "tenant_isolated": repository.authorization_inputs(
            tenant_id="tenant-b", subject_id="user-a"
        ) == {"roles": [], "groups": [], "group_members": [], "group_roles": []},
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_authorization_repository_evidence.v1",
        "slice": "1235",
        "requirement": "S124",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_authorization_repository_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "record_count": sum(len(value) for value in snapshot.values()),
            "event_count": len(events),
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_authorization_repository="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"records={summary.get('record_count', 0)} events={summary.get('event_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_authorization_repository()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
