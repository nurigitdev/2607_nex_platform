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

from fastapi.testclient import TestClient  # noqa: E402

from nex_ae_api.prompts import seed_ae_prompt_registry  # noqa: E402
from nex_ae_api.runtime_policy_api import register_runtime_policy_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)
from nex_runtime.prompts import PromptRegistryStore  # noqa: E402


def run_ae_runtime_policy_api() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = PromptRegistryStore()
    seed_ae_prompt_registry(store)
    register_runtime_policy_routes(app, store=store)
    client = TestClient(app)
    service = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-ae-api",
    )
    browser = issue_mock_user_token(tenant_id="tenant-smoke", user_id="user-smoke")
    service_headers = {"Authorization": f"Bearer {service.access_token}"}
    browser_headers = {"Authorization": f"Bearer {browser.access_token}"}

    denied = client.get("/api/v1/runtime-policies")
    catalog = client.get("/api/v1/runtime-policies", headers=service_headers)
    resolved = client.post(
        "/api/v1/runtime-policies/resolve",
        headers=browser_headers,
        json={"user_message": "private smoke question"},
    )
    binding = client.get(
        "/api/v1/runtime-policies/prompt-bindings/ae.general_answer.default",
        headers=service_headers,
    )
    serialized = json.dumps(
        {"catalog": catalog.json(), "resolved": resolved.json(), "binding": binding.json()},
        sort_keys=True,
    )
    checks = {
        "unauthorized_rejected": denied.status_code == 401,
        "catalog_ok": catalog.status_code == 200,
        "six_rules_visible": len(catalog.json().get("policies", [])) == 6,
        "service_auth_accepted": catalog.status_code == 200,
        "browser_auth_accepted": resolved.status_code == 200,
        "exact_rule": resolved.json().get("compatibility_rule", {}).get("rule_id")
        == "ae.general_answer.v1",
        "binding_resolved": resolved.json().get("prompt_binding", {}).get("binding_key")
        == "ae.general_answer.default",
        "binding_inspection_ok": binding.status_code == 200,
        "content_excluded": '"content"' not in serialized,
        "private_prompt_excluded": "private smoke question" not in serialized,
        "provider_runtime_excluded": "api_key" not in serialized,
    }
    return {
        "smoke_schema_version": "ae_runtime_policy_api_smoke.v1",
        "slice": "1026",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "remote_provider_required": False,
        "postgresql_required": False,
        "next_slice": "1027",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "ae_runtime_policy_api="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_runtime_policy_api()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
