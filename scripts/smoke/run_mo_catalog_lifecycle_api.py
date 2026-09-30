#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-mo"):
    sys.path.insert(0, str(path))

from nex_mo.catalog_lifecycle_api import register_catalog_lifecycle_routes  # noqa: E402
from nex_mo.catalog_lifecycle_repository import (  # noqa: E402
    InMemoryCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402


NOW = "2026-10-01T03:00:00Z"


def run_mo_catalog_lifecycle_api() -> dict[str, Any]:
    repository = InMemoryCatalogLifecycleRepository()
    service = CatalogLifecycleService(repository, clock=lambda: NOW)
    service.ensure_bootstrap()
    app = FastAPI()
    register_catalog_lifecycle_routes(app, service=service)
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    unauthorized = client.get("/api/v1/model-catalog")
    catalog = client.get("/api/v1/model-catalog", headers=headers)
    aliases = client.get(
        "/api/v1/provider-alias-bindings?state=ACTIVE",
        headers=headers,
    )
    serialized = json.dumps(
        {"catalog": catalog.json(), "aliases": aliases.json()},
        sort_keys=True,
    )
    forbidden = [
        field
        for field in (
            "provider_endpoint",
            "provider_api_key",
            "model_path",
            "database_url",
            "changed_by",
        )
        if field in serialized
    ]
    checks = {
        "unauthorized_rejected": unauthorized.status_code == 401,
        "catalog_read_succeeded": catalog.status_code == 200
        and len(catalog.json().get("data", [])) == 3,
        "alias_read_succeeded": aliases.status_code == 200
        and len(aliases.json().get("data", [])) == 3,
        "private_fields_omitted": not forbidden,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_catalog_lifecycle_api.v1",
        "slice": "1177",
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_catalog_lifecycle_api_failed",
        "checks": checks,
        "summary": {
            "unauthorized_status": unauthorized.status_code,
            "catalog_entry_count": len(catalog.json().get("data", [])),
            "active_alias_count": len(aliases.json().get("data", [])),
            "exposed_private_field_count": len(forbidden),
        },
        "issues": forbidden,
        "next_slice": "1178" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_catalog_lifecycle_api="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"unauthorized={summary.get('unauthorized_status', 0)} "
        f"entries={summary.get('catalog_entry_count', 0)} "
        f"aliases={summary.get('active_alias_count', 0)} "
        f"private_fields={summary.get('exposed_private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_catalog_lifecycle_api()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
