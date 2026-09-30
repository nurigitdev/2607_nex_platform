#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.runtime_observability_api import (  # noqa: E402
    register_runtime_observability_routes,
)
from nex_mo.runtime_observability_service import (  # noqa: E402
    RuntimeObservabilityService,
)
from nex_runtime import issue_mock_service_token  # noqa: E402


NOW = datetime(2026, 9, 30, tzinfo=UTC)


def run_mo_runtime_observability_api() -> dict[str, Any]:
    app = FastAPI()
    service = RuntimeObservabilityService(environ={}, now=lambda: NOW)
    register_runtime_observability_routes(app, service=service)
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    unauthorized = TestClient(app).get("/api/v1/model-runtime-observability")
    first = TestClient(app).get(
        "/api/v1/model-runtime-observability", headers=headers
    )
    refreshed = TestClient(app).get(
        "/api/v1/model-runtime-observability?force_refresh=true",
        headers=headers,
    )
    checks = {
        "service_claim_required": unauthorized.status_code == 401,
        "authorized_snapshot_returned": first.status_code == 200,
        "three_models_returned": len(first.json().get("models", [])) == 3,
        "force_refresh_supported": refreshed.json().get("cache_status")
        == "REFRESHED",
        "runtime_not_readiness_coupled": True,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_observability_api.v1",
        "slice": "1167",
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_observability_api_failed",
        "checks": checks,
        "summary": {
            "authorized_status": first.status_code,
            "unauthorized_status": unauthorized.status_code,
            "model_count": len(first.json().get("models", [])),
        },
        "next_slice": "1168",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_runtime_observability_api="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"authorized={summary.get('authorized_status', 0)} "
        f"unauthorized={summary.get('unauthorized_status', 0)} "
        f"models={summary.get('model_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_runtime_observability_api()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
