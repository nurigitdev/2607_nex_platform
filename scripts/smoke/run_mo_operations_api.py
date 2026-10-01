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
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-mo"):
    sys.path.insert(0, str(path))

from nex_mo.catalog_lifecycle_repository import InMemoryCatalogLifecycleRepository  # noqa: E402
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService  # noqa: E402
from nex_mo.operations_api import register_operations_routes  # noqa: E402
from nex_mo.operations_service import MOOperationsService  # noqa: E402
from nex_mo.provider_readiness_service import ProviderReadinessService  # noqa: E402
from nex_mo.runtime_observability_service import RuntimeObservabilityService  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402


NOW = datetime(2026, 10, 1, tzinfo=UTC)


def run_mo_operations_api() -> dict[str, Any]:
    catalog = CatalogLifecycleService(
        InMemoryCatalogLifecycleRepository(),
        clock=lambda: "2026-10-01T00:00:00Z",
    )
    catalog.ensure_bootstrap()
    telemetry = [
        {
            "capability": capability,
            "configured": False,
            "request_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "degraded_count": 0,
        }
        for capability in ("embedding", "reranking", "generation")
    ]
    service = MOOperationsService(
        catalog_service=catalog,
        readiness_service=ProviderReadinessService(environ={}, now=lambda: NOW),
        runtime_service=RuntimeObservabilityService(environ={}, now=lambda: NOW),
        telemetry_reader=lambda: telemetry,
        environ={},
        now=lambda: NOW,
    )
    app = FastAPI()
    register_operations_routes(app, service=service)
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    unauthorized = client.get("/api/v1/operations-snapshot")
    authorized = client.get(
        "/api/v1/operations-snapshot?force_refresh=true",
        headers=headers,
    )
    payload = authorized.json()
    serialized = json.dumps(payload, sort_keys=True)
    forbidden = ("provider_api_key", "database_url", "model_path", "ssh_target")
    passed = (
        unauthorized.status_code == 401
        and authorized.status_code == 200
        and payload.get("operations_status") == "READY"
        and not any(item in serialized for item in forbidden)
    )
    return {
        "evidence_schema_version": "mo_operations_api_evidence.v1",
        "slice": "1185",
        "requirement": "S119",
        "status": "PASS" if passed else "FAIL",
        "summary": {
            "unauthorized_status": unauthorized.status_code,
            "authorized_status": authorized.status_code,
            "source_count": payload.get("summary", {}).get("source_count", 0),
            "capability_count": payload.get("summary", {}).get(
                "capability_count", 0
            ),
            "private_field_count": sum(item in serialized for item in forbidden),
        },
        "next_slice": "1186" if passed else None,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_operations_api="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"auth={summary.get('unauthorized_status', 0)}/"
        f"{summary.get('authorized_status', 0)} "
        f"sources={summary.get('source_count', 0)} "
        f"capabilities={summary.get('capability_count', 0)} "
        f"private={summary.get('private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_operations_api()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
