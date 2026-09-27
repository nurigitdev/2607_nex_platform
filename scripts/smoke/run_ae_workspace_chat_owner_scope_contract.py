#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.auth_guard import BrowserUserAuthContext
from nex_ae_api.route_auth import AeFacadeRouteAuthContext
from nex_ae_api.workspace_chat_auth import (
    WorkspaceChatOwnerError,
    browser_owner_scope,
    owner_scoped_payload,
    record_matches_owner,
)


def run_owner_scope_contract() -> dict[str, Any]:
    browser = AeFacadeRouteAuthContext(
        auth_mode="browser_user",
        browser_context=BrowserUserAuthContext(
            tenant_id="tenant-a",
            user_id="user-a",
            scopes=("user",),
            roles=("employee",),
        ),
    )
    service = AeFacadeRouteAuthContext(auth_mode="service")
    normalized, browser_scope = owner_scoped_payload({}, browser)
    service_payload, service_scope = owner_scoped_payload(
        {"tenant_id": "tenant-a", "owner_user_id": "user-a"},
        service,
    )
    missing_rejected = False
    try:
        owner_scoped_payload({}, service)
    except WorkspaceChatOwnerError:
        missing_rejected = True
    checks = {
        "browser_claim_authoritative": normalized["tenant_id"] == "tenant-a"
        and normalized["owner_user_id"] == "user-a",
        "service_scope_explicit": service_payload["tenant_id"] == "tenant-a"
        and service_scope.authority == "service_payload",
        "canonical_ref_present": normalized["ownership_ref"]["owner_subject_ref"]["id"]
        == "user-a",
        "missing_service_scope_rejected": missing_rejected,
        "same_owner_visible": record_matches_owner(normalized, browser_scope),
        "cross_owner_hidden": not record_matches_owner(
            {**normalized, "owner_user_id": "user-b", "user_id": "user-b"},
            browser_scope,
        ),
        "browser_scope_recoverable": browser_owner_scope(browser) == browser_scope,
        "service_has_no_browser_scope": browser_owner_scope(service) is None,
    }
    return {
        "contract_schema_version": "ae_workspace_chat_owner_scope_contract.v1",
        "slice": "1013",
        "requirement": "S102",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "owner_scope": browser_scope.to_wire(),
        "private_fields_included": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    passed = sum(bool(value) for value in result.get("checks", {}).values())
    total = len(result.get("checks", {}))
    return (
        "ae_workspace_chat_owner_scope="
        f"{str(result.get('status', 'FAIL')).lower()} checks={passed}/{total} "
        f"private_fields={result.get('private_fields_included', False)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_owner_scope_contract()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
