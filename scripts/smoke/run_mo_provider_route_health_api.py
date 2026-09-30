#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.main import PROVIDER_READINESS, app  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402


def run_mo_provider_route_health_api() -> dict[str, Any]:
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    with patch.dict(os.environ, {"NEX_MO_PROVIDER_MODE": "mock"}):
        PROVIDER_READINESS.clear()
        client = TestClient(app)
        unauthorized = client.get("/api/v1/provider-route-health")
        response = client.get("/api/v1/provider-route-health", headers=headers)
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    checks = {
        "service_claim_required": unauthorized.status_code == 401,
        "authorized_query_succeeds": response.status_code == 200,
        "provider_readiness_ready": payload["readiness_status"] == "READY",
        "three_routes_projected": payload["summary"]["route_count"] == 3,
        "private_fields_omitted": all(
            field not in serialized
            for field in (
                "provider_endpoint",
                "provider_api_key",
                "model_path",
                "request_payload",
                "response_payload",
            )
        ),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_route_health_api.v1",
        "slice": "1129",
        "requirement": "S113",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_route_health_api_failed",
        "checks": checks,
        "summary": {
            "http_status": response.status_code,
            "route_count": payload.get("summary", {}).get("route_count", 0),
            "unauthorized_status": unauthorized.status_code,
        },
        "issues": [],
        "next_slice": "1130",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_route_health_api="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"http={summary.get('http_status', 0)} "
        f"routes={summary.get('route_count', 0)} "
        f"unauthorized={summary.get('unauthorized_status', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_route_health_api()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
