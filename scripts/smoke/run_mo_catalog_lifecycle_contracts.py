#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-mo"):
    sys.path.insert(0, str(path))

from nex_mo.contract_api_drift_audit import (  # noqa: E402
    build_mo_contract_api_drift_audit,
)
from nex_mo.main import app  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402


CATALOG_SCHEMA = ROOT / "contracts/schemas/service/nex_mo/model_catalog_collection.v1.schema.json"
ALIAS_SCHEMA = ROOT / "contracts/schemas/service/nex_mo/alias_binding_collection.v1.schema.json"


def run_mo_catalog_lifecycle_contracts() -> dict[str, Any]:
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    catalog = client.get("/api/v1/model-catalog", headers=headers)
    aliases = client.get("/api/v1/provider-alias-bindings", headers=headers)
    unauthorized = (
        client.get("/api/v1/model-catalog"),
        client.post("/api/v1/model-catalog", json={}),
        client.get("/api/v1/model-catalog/catalog:missing"),
        client.post(
            "/api/v1/model-catalog/catalog:missing/transitions",
            json={},
        ),
        client.get("/api/v1/provider-alias-bindings"),
        client.post("/api/v1/provider-alias-bindings/activate", json={}),
        client.post("/api/v1/provider-alias-bindings/rollback", json={}),
    )
    validation_errors: list[str] = []
    for schema_path, response in (
        (CATALOG_SCHEMA, catalog),
        (ALIAS_SCHEMA, aliases),
    ):
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(response.json())
        except Exception as exc:
            validation_errors.append(type(exc).__name__)
    serialized = json.dumps(
        {"catalog": catalog.json(), "aliases": aliases.json()},
        sort_keys=True,
    )
    forbidden = [
        field
        for field in (
            "changed_by",
            "provider_endpoint",
            "provider_api_key",
            "model_path",
            "database_url",
        )
        if field in serialized
    ]
    drift = build_mo_contract_api_drift_audit(ROOT)
    checks = {
        "catalog_response_valid": catalog.status_code == 200
        and not validation_errors,
        "alias_response_valid": aliases.status_code == 200
        and not validation_errors,
        "all_operations_authenticated": all(
            response.status_code == 401 for response in unauthorized
        ),
        "runtime_openapi_parity_zero": drift["status"] == "PASS"
        and drift["summary"]["runtime_operation_count"] == 27
        and drift["summary"]["drift_count"] == 0,
        "private_fields_omitted": not forbidden,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_catalog_lifecycle_contracts.v1",
        "slice": "1179",
        "requirement": "S118",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_catalog_lifecycle_contracts_failed",
        "checks": checks,
        "summary": {
            "catalog_entry_count": len(catalog.json().get("data", [])),
            "active_alias_count": len(aliases.json().get("data", [])),
            "unauthorized_rejection_count": sum(
                response.status_code == 401 for response in unauthorized
            ),
            "runtime_operation_count": drift["summary"]["runtime_operation_count"],
            "contract_drift_count": drift["summary"]["drift_count"],
            "schema_validation_error_count": len(validation_errors),
            "exposed_private_field_count": len(forbidden),
        },
        "issues": [*validation_errors, *forbidden],
        "next_slice": "1180" if passed else "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_catalog_lifecycle_contracts="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"operations={summary.get('runtime_operation_count', 0)} "
        f"auth={summary.get('unauthorized_rejection_count', 0)}/7 "
        f"drift={summary.get('contract_drift_count', -1)} "
        f"private={summary.get('exposed_private_field_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_catalog_lifecycle_contracts()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
