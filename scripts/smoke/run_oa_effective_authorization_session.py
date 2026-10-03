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
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver  # noqa: E402
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry  # noqa: E402
from nex_oa.sessions import InMemoryOaSessionRegistry  # noqa: E402


CONTEXT = {
    "actor_ref": "nex.service:nex-ag",
    "request_id": "request-1236",
    "trace_id": "trace-1236",
}


def run_oa_effective_authorization_session() -> dict[str, Any]:
    memberships = InMemoryOaTenantMembershipRegistry()
    memberships.ensure_membership(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "roles": ["employee"],
            "scopes": ["user:session"],
        }
    )
    authorization = InMemoryOaAuthorizationRepository()
    authorization.upsert_role(
        {
            "tenant_id": "tenant-a",
            "role_id": "editor",
            "scopes": ["document:read", "document:write"],
        },
        context=CONTEXT,
    )
    authorization.upsert_group(
        {"tenant_id": "tenant-a", "group_id": "engineering"},
        context=CONTEXT,
    )
    authorization.upsert_group_member(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "subject_id": "user-a",
        },
        context=CONTEXT,
    )
    authorization.upsert_group_role(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "role_id": "editor",
        },
        context=CONTEXT,
    )
    resolver = OaEffectiveAuthorizationResolver(authorization)
    sessions = InMemoryOaSessionRegistry(
        membership_registry=memberships,
        authorization_resolver=resolver,
    )
    issued = sessions.issue_session(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "requested_scopes": ["document:write"],
        }
    )
    session = issued["session"]
    membership = memberships.get_membership(
        tenant_id="tenant-a",
        subject_id="user-a",
    )
    assert membership is not None
    checks = {
        "group_role_in_claims": "editor" in session["roles"],
        "direct_role_compatible": "employee" in session["roles"],
        "group_scope_granted": session["scopes"] == ["document:write"],
        "owner_scope_preserved": session["tenant_ref"]["id"] == "tenant-a"
        and session["subject_ref"]["id"] == "user-a",
        "session_opaque": bool(session["session_id"]),
        "resolver_revision_hash_stable": len(
            resolver.resolve(membership)["revision_hash"]
        )
        == 64,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_effective_authorization_session_evidence.v1",
        "slice": "1236",
        "requirement": "S124",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "oa_effective_authorization_session_failed"
        ),
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "claim_role_count": len(session["roles"]),
            "claim_scope_count": len(session["scopes"]),
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_effective_authorization_session="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"claims={summary.get('claim_role_count', 0)}/{summary.get('claim_scope_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_effective_authorization_session()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
