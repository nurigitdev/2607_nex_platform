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
from nex_oa.identity_lifecycle_repository import InMemoryOaIdentityLifecycleRepository  # noqa: E402
from nex_oa.identity_lifecycle_service import (  # noqa: E402
    OA_IDENTITY_LIFECYCLE_WRITE_SCOPE,
    OaIdentityLifecycleService,
    register_identity_lifecycle_routes,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry  # noqa: E402
from nex_oa.subjects import InMemoryOaSubjectRegistry  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


def run_oa_membership_lifecycle_api() -> dict[str, Any]:
    subjects = InMemoryOaSubjectRegistry()
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    memberships.ensure_membership(
        {"tenant_id": "tenant-1217", "subject_id": "employee-1217"}
    )
    repository = InMemoryOaIdentityLifecycleRepository(subjects, memberships)
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_identity_lifecycle_routes(
        app,
        service=OaIdentityLifecycleService(subjects, memberships, repository),
    )
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, OA_IDENTITY_LIFECYCLE_WRITE_SCOPE],
    )
    path = "/internal/v1/identity/tenants/tenant-1217/memberships/employee-1217/lifecycle"
    response = TestClient(app).patch(
        path,
        json={
            "target_status": "DISABLED",
            "expected_revision": 1,
            "reason_code": "admin.membership-disable",
        },
        headers={
            "Authorization": f"Bearer {token.access_token}",
            "X-Request-ID": "request-1217",
            "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
        },
    )
    body = response.json()
    checks = {
        "protected_transition_succeeds": response.status_code == 200,
        "membership_disabled": body.get("status") == "DISABLED",
        "revision_advanced": body.get("revision") == 2,
        "invalidation_requested": repository.events[0]["target_status"] == "DISABLED",
        "actor_derived_from_claim": repository.events[0]["actor_ref_id"] == "nex-ag",
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_membership_lifecycle_api_evidence.v1",
        "slice": "1217",
        "requirement": "S122",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_membership_lifecycle_api_failed",
        "checks": checks,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_membership_lifecycle_api=pass checks=5/5"
        if evidence.get("status") == "PASS"
        else "oa_membership_lifecycle_api=fail"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_membership_lifecycle_api()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
