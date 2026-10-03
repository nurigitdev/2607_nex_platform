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

from fastapi.testclient import TestClient  # noqa: E402

from nex_oa.authorization_repository import (  # noqa: E402
    InMemoryOaAuthorizationRepository,
    bind_authorization_session_registry,
)
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver  # noqa: E402
from nex_oa.authorization_service import (  # noqa: E402
    OA_AUTHORIZATION_ADMIN_SCOPE,
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry  # noqa: E402
from nex_oa.sessions import InMemoryOaSessionRegistry  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


def _headers(scope: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, scope],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-1237",
    }


def run_oa_authorization_admin_api() -> dict[str, Any]:
    memberships = InMemoryOaTenantMembershipRegistry()
    memberships.ensure_membership(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "roles": ["employee"],
            "scopes": ["user:session"],
        }
    )
    repository = InMemoryOaAuthorizationRepository()
    resolver = OaEffectiveAuthorizationResolver(repository)
    sessions = InMemoryOaSessionRegistry(memberships, resolver)
    bind_authorization_session_registry(repository, sessions)
    service = OaAuthorizationService(repository, resolver, memberships)
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_authorization_routes(app, service=service)
    client = TestClient(app)
    admin = _headers(OA_AUTHORIZATION_ADMIN_SCOPE)
    reader = _headers(OA_AUTHORIZATION_READ_SCOPE)
    base = "/internal/v1/auth/tenants/tenant-a"

    role = client.put(
        f"{base}/roles/editor",
        json={"scopes": ["document:read"], "expected_revision": 0},
        headers=admin,
    )
    group = client.put(
        f"{base}/groups/engineering",
        json={"expected_revision": 0},
        headers=admin,
    )
    member = client.put(
        f"{base}/groups/engineering/members/user-a",
        json={"expected_revision": 0},
        headers=admin,
    )
    issued = sessions.issue_session(
        {"tenant_id": "tenant-a", "subject_id": "user-a"}
    )
    assignment = client.put(
        f"{base}/groups/engineering/roles/editor",
        json={"expected_revision": 0},
        headers=admin,
    )
    effective = client.get(
        f"{base}/subjects/user-a/authorization",
        headers=reader,
    )
    events = client.get(f"{base}/authorization-events", headers=reader)
    denied = client.get(
        f"{base}/subjects/user-a/authorization",
        headers=admin,
    )

    session_id = issued["session"]["session_id"]
    checks = {
        "role_upserted": role.status_code == 200,
        "group_upserted": group.status_code == 200,
        "member_upserted": member.status_code == 200,
        "assignment_upserted": assignment.status_code == 200,
        "affected_session_revoked": assignment.json().get("revoked_session_count") == 1
        and sessions.sessions[session_id]["status"] == "REVOKED",
        "effective_grants_read": effective.status_code == 200
        and "editor" in effective.json().get("authorization", {}).get("roles", []),
        "events_append_only": events.status_code == 200
        and events.json().get("count") == 4,
        "read_scope_separated": denied.status_code == 403,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_authorization_admin_api_evidence.v1",
        "slice": "1237",
        "requirement": "S124",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_authorization_admin_api_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "event_count": events.json().get("count", 0),
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_authorization_admin_api="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"events={summary.get('event_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_authorization_admin_api()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
