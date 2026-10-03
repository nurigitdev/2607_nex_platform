#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-ag"))

from nex_ag.federated_operator_authorization import (  # noqa: E402
    ag_federated_authorization_audit_from_request,
)
from nex_ag.federated_operator_context import (  # noqa: E402
    AG_FEDERATED_OPERATOR_CONTEXT_HEADER,
    ag_federated_operator_context_from_request,
    encode_ag_federated_operator_context_header,
)
from nex_ag.service_auth import authorize_ag_service_or_admin_request  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/admin")
    def admin(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = authorize_ag_service_or_admin_request(
            request,
            authorization,
            admin_error_code="AG_ADMIN_REQUIRED",
            admin_error_detail="Admin role is required.",
        )
        audit = ag_federated_authorization_audit_from_request(request)
        if denied is not None:
            if audit is not None:
                denied.headers["X-NEX-Audit-Outcome"] = audit.outcome
            return denied
        context = ag_federated_operator_context_from_request(request)
        return {
            "authorized": True,
            "operator_ref": context.operator_ref() if context else None,
            "audit": audit.to_wire() if audit else None,
        }

    return TestClient(app)


def _headers(*, roles: list[str], caller: str = "nex-ae-api") -> dict[str, str]:
    token = issue_mock_service_token(service_id=caller, audience="nex-ag")
    context = encode_ag_federated_operator_context_header(
        {
            "tenant_id": "company",
            "subject_id": "employee-1001",
            "roles": roles,
            "scopes": ["workspace:use"],
            "auth_method": "federated_oidc",
            "session_id_digest": "a" * 64,
        }
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        AG_FEDERATED_OPERATOR_CONTEXT_HEADER: context,
    }


def run_ag_federated_authorization_hardening() -> dict[str, Any]:
    client = _client()
    allowed = client.get("/admin", headers=_headers(roles=["admin"]))
    viewer = client.get("/admin", headers=_headers(roles=["viewer"]))
    wrong_caller = client.get(
        "/admin", headers=_headers(roles=["admin"], caller="nex-cx")
    )
    serialized = json.dumps(allowed.json(), sort_keys=True).lower()
    checks = {
        "ae_admin_authorized": allowed.status_code == 200,
        "operator_ref_adopted": allowed.json().get("operator_ref")
        == {"operator_type": "user", "operator_id": "employee-1001"},
        "viewer_denied": viewer.status_code == 403
        and viewer.json().get("error_code") == "AG_ADMIN_REQUIRED",
        "wrong_caller_denied": wrong_caller.status_code == 403
        and wrong_caller.json().get("error_code")
        == "AG_FEDERATED_OPERATOR_CALLER_FORBIDDEN",
        "audit_authorized": allowed.json().get("audit", {}).get("outcome")
        == "AUTHORIZED",
        "denial_audited": viewer.headers.get("X-NEX-Audit-Outcome") == "DENIED",
        "audit_privacy_safe": all(
            value not in serialized
            for value in ("authorization", "id_token", "external_subject", "provider_id")
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "ag_federated_authorization_evidence.v1",
        "slice": "1288",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ag_federated_authorization_failed",
        "checks": checks,
        "next_slice": "1289" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    return (
        "ag_federated_authorization="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_federated_authorization_hardening()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
