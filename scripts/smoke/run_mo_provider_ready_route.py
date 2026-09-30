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


def run_mo_provider_ready_route() -> dict[str, Any]:
    database_check = {
        "name": "database",
        "ok": True,
        "database_env": "NEX_MO_DATABASE_URL",
        "database_name": "nex_mo_test",
        "database_user": "nex_mo_user",
        "latency_ms": 1,
    }
    with (
        patch.dict(os.environ, {"NEX_MO_PROVIDER_MODE": "mock"}),
        patch(
            "nex_runtime.app.check_database_readiness",
            return_value=database_check,
        ),
    ):
        PROVIDER_READINESS.clear()
        response = TestClient(app).get("/ready")
    payload = response.json()
    serialized = json.dumps(payload, sort_keys=True)
    checks = {
        "ready_route_returns_200": response.status_code == 200,
        "database_and_provider_composed": [
            item["name"] for item in payload["checks"]
        ]
        == ["database", "provider_routes"],
        "aggregate_ready": payload["readiness_status"] == "READY",
        "three_provider_routes_ready": payload["checks"][1]["summary"][
            "status_counts"
        ]["READY"]
        == 3,
        "private_fields_omitted": all(
            field not in serialized
            for field in ("provider_endpoint", "provider_api_key", "model_path")
        ),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_ready_route.v1",
        "slice": "1128",
        "requirement": "S113",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_ready_route_failed",
        "checks": checks,
        "summary": {
            "readiness_check_count": len(payload.get("checks", [])),
            "ready_provider_route_count": payload.get("checks", [{}, {}])[1]
            .get("summary", {})
            .get("status_counts", {})
            .get("READY", 0),
        },
        "issues": [],
        "next_slice": "1129",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_ready_route="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('readiness_check_count', 0)} "
        f"provider_routes={summary.get('ready_provider_route_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_ready_route()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
