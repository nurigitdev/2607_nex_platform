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

from nex_oa.authorization import (  # noqa: E402
    OaAuthorizationError,
    plan_group_member_upsert,
    plan_group_role_upsert,
    plan_group_upsert,
    plan_role_upsert,
)


def run_oa_group_role_authorization_domain() -> dict[str, Any]:
    role = plan_role_upsert(
        {
            "tenant_id": "tenant-a",
            "role_id": "knowledge-editor",
            "display_name": "Knowledge Editor",
            "scopes": ["document:read", "document:write", "document:read"],
            "expected_revision": 0,
        }
    )
    group = plan_group_upsert(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "display_name": "Engineering",
            "expected_revision": 0,
        }
    )
    member = plan_group_member_upsert(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "subject_id": "user-a",
            "expected_revision": 0,
        }
    )
    assignment = plan_group_role_upsert(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "role_id": "knowledge-editor",
            "expected_revision": 0,
        }
    )
    conflict_closed = False
    try:
        plan_role_upsert(
            {**role, "expected_revision": 0},
            current=role,
        )
    except OaAuthorizationError as exc:
        conflict_closed = exc.status_code == 409
    checks = {
        "role_revision_created": role["revision"] == 1,
        "scope_set_normalized": role["scopes"] == ("document:read", "document:write"),
        "group_revision_created": group["revision"] == 1,
        "member_is_tenant_scoped": member["tenant_id"] == group["tenant_id"],
        "assignment_links_group_role": (
            assignment["group_id"] == group["group_id"]
            and assignment["role_id"] == role["role_id"]
        ),
        "revision_conflict_fails_closed": conflict_closed,
    }
    passed = all(checks.values())
    return {
        "domain_schema_version": "oa_group_role_authorization_domain_evidence.v1",
        "slice": "1233",
        "requirement": "S124",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_group_role_authorization_domain_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "role_scope_count": len(role["scopes"]),
            "entity_count": 4,
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_group_role_authorization_domain="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"entities={summary.get('entity_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_group_role_authorization_domain()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
