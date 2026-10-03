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

from nex_oa.authorization_repository import InMemoryOaAuthorizationRepository  # noqa: E402
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver  # noqa: E402
from nex_oa.authorization_service import (  # noqa: E402
    OA_AUTHORIZATION_ADMIN_SCOPE,
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.memberships import (  # noqa: E402
    InMemoryOaTenantMembershipRegistry,
    register_identity_membership_routes,
)
from nex_oa.subjects import (  # noqa: E402
    InMemoryOaSubjectRegistry,
    OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE,
    register_subject_registry_routes,
)
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


def _headers(*scopes: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-1238",
    }


def run_oa_authorization_scope_hardening() -> dict[str, Any]:
    subjects = InMemoryOaSubjectRegistry()
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    repository = InMemoryOaAuthorizationRepository()
    resolver = OaEffectiveAuthorizationResolver(repository)
    service = OaAuthorizationService(repository, resolver, memberships)
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_subject_registry_routes(app, registry=subjects)
    register_identity_membership_routes(app, registry=memberships)
    register_authorization_routes(app, service=service)
    client = TestClient(app)

    service_headers = _headers()
    bootstrap_headers = _headers(OA_IDENTITY_BOOTSTRAP_WRITE_SCOPE)
    admin_headers = _headers(OA_AUTHORIZATION_ADMIN_SCOPE)
    read_headers = _headers(OA_AUTHORIZATION_READ_SCOPE)
    subject_path = "/internal/v1/subject-registry/ensure"
    membership_path = "/internal/v1/identity/memberships/ensure"
    subject_payload = {"tenant_id": "tenant-a", "subject_id": "user-a"}

    missing = client.post(subject_path, json=subject_payload)
    basic_denied = client.post(
        subject_path,
        json=subject_payload,
        headers=service_headers,
    )
    admin_denied = client.post(
        subject_path,
        json=subject_payload,
        headers=admin_headers,
    )
    subject = client.post(
        subject_path,
        json=subject_payload,
        headers=bootstrap_headers,
    )
    membership_denied = client.post(
        membership_path,
        json=subject_payload,
        headers=service_headers,
    )
    membership = client.post(
        membership_path,
        json=subject_payload,
        headers=bootstrap_headers,
    )
    readback = client.get(
        "/internal/v1/identity/memberships/tenants/tenant-a/subjects/user-a",
        headers=service_headers,
    )
    bootstrap_cannot_admin = client.put(
        "/internal/v1/auth/tenants/tenant-a/roles/editor",
        json={"scopes": ["document:read"], "expected_revision": 0},
        headers=bootstrap_headers,
    )
    admin = client.put(
        "/internal/v1/auth/tenants/tenant-a/roles/editor",
        json={"scopes": ["document:read"], "expected_revision": 0},
        headers=admin_headers,
    )
    effective = client.get(
        "/internal/v1/auth/tenants/tenant-a/subjects/user-a/authorization",
        headers=read_headers,
    )

    checks = {
        "missing_claim_rejected": missing.status_code == 401,
        "service_only_bootstrap_rejected": basic_denied.status_code == 403,
        "admin_not_bootstrap": admin_denied.status_code == 403,
        "subject_bootstrap_accepted": subject.status_code == 200,
        "membership_scope_enforced": membership_denied.status_code == 403,
        "membership_bootstrap_accepted": membership.status_code == 200,
        "compatibility_read_preserved": readback.status_code == 200,
        "bootstrap_not_admin": bootstrap_cannot_admin.status_code == 403,
        "admin_mutation_accepted": admin.status_code == 200,
        "read_scope_accepted": effective.status_code == 200,
        "private_values_absent": all(
            marker
            not in json.dumps(
                [subject.json(), membership.json(), effective.json()]
            ).lower()
            for marker in ('"password":', '"access_token":', '"cookie":')
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_authorization_scope_hardening_evidence.v1",
        "slice": "1238",
        "requirement": "S124",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_authorization_scope_hardening_failed",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "dedicated_scope_count": 3,
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_authorization_scope_hardening="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"checks={summary.get('passed_check_count', 0)}/{summary.get('check_count', 0)} "
        f"scopes={summary.get('dedicated_scope_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_authorization_scope_hardening()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
