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
from nex_oa.identity_lifecycle_repository import (  # noqa: E402
    InMemoryOaIdentityLifecycleRepository,
)
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


def run_oa_subject_lifecycle_api() -> dict[str, Any]:
    subjects = InMemoryOaSubjectRegistry()
    subjects.ensure_subject({"tenant_id": "tenant-1216", "subject_id": "employee-1216"})
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    repository = InMemoryOaIdentityLifecycleRepository(subjects, memberships)
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_identity_lifecycle_routes(
        app,
        service=OaIdentityLifecycleService(subjects, repository),
    )
    client = TestClient(app)
    path = "/internal/v1/identity/tenants/tenant-1216/subjects/employee-1216/lifecycle"
    payload = {
        "target_status": "DISABLED",
        "expected_revision": 1,
        "reason_code": "admin.disable",
    }
    denied_token = issue_mock_service_token(
        service_id="nex-ag", audience="nex-oa", scopes=[DEFAULT_SERVICE_SCOPE]
    )
    allowed_token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, OA_IDENTITY_LIFECYCLE_WRITE_SCOPE],
    )
    denied = client.patch(
        path,
        json=payload,
        headers={"Authorization": f"Bearer {denied_token.access_token}"},
    )
    accepted = client.patch(
        path,
        json=payload,
        headers={
            "Authorization": f"Bearer {allowed_token.access_token}",
            "X-Request-ID": "request-1216",
            "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
        },
    )
    body = accepted.json()
    checks = {
        "dedicated_scope_required": denied.status_code == 403,
        "protected_transition_succeeds": accepted.status_code == 200,
        "revision_advanced": body.get("revision") == 2,
        "server_actor_recorded": repository.events[0]["actor_ref_id"] == "nex-ag",
        "request_trace_propagated": body.get("request_id") == "request-1216",
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_subject_lifecycle_api_evidence.v1",
        "slice": "1216",
        "requirement": "S122",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_subject_lifecycle_api_failed",
        "checks": checks,
        "response_status": accepted.status_code,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "oa_subject_lifecycle_api=pass checks=5/5"
        if evidence.get("status") == "PASS"
        else "oa_subject_lifecycle_api=fail"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_subject_lifecycle_api()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
