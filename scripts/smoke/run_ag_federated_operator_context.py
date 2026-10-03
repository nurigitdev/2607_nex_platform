#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "services/nex-ag"))

from nex_ag.federated_operator_context import (  # noqa: E402
    adopt_ag_federated_operator_context,
    ag_federated_operator_context_from_request,
)
from nex_oa.federated_login import build_federated_login_response  # noqa: E402


def run_ag_federated_operator_context() -> dict[str, Any]:
    oa_response = build_federated_login_response(
        {
            "session": {
                "session_id": "private-browser-session",
                "tenant_ref": {"type": "oa_tenant", "id": "company"},
                "subject_ref": {"type": "oa_user", "id": "employee-1001"},
                "roles": ["admin"],
                "scopes": ["workspace:use"],
            },
            "metadata": {},
        },
        provider_id="company-oidc",
    )
    request = SimpleNamespace(state=SimpleNamespace())
    adopted = adopt_ag_federated_operator_context(
        request, oa_response["operator_context"]
    )
    restored = ag_federated_operator_context_from_request(request)
    wire = adopted.to_wire()
    serialized = json.dumps(wire, sort_keys=True).lower()
    checks = {
        "oa_context_emitted": set(wire) == {
            "tenant_id",
            "subject_id",
            "roles",
            "scopes",
            "auth_method",
            "session_id_digest",
        },
        "canonical_subject_adopted": adopted.tenant_id == "company"
        and adopted.subject_id == "employee-1001",
        "authorization_adopted": adopted.roles == ("admin",)
        and adopted.scopes == ("workspace:use",),
        "federated_method_preserved": adopted.auth_method == "federated_oidc",
        "session_digest_bounded": len(adopted.session_id_digest) == 64,
        "request_state_bound": restored is adopted,
        "operator_ref_safe": adopted.operator_ref()
        == {"operator_type": "user", "operator_id": "employee-1001"},
        "private_values_absent": all(
            value not in serialized
            for value in (
                "private-browser-session",
                "company-oidc",
                "id_token",
                "external_subject",
            )
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "ag_federated_operator_context_evidence.v1",
        "slice": "1287",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "ag_federated_operator_context_failed",
        "checks": checks,
        "operator_context": wire,
        "next_slice": "1288" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    context = evidence.get("operator_context") or {}
    return (
        "ag_federated_operator_context="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"method={context.get('auth_method', 'missing')} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_federated_operator_context()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
