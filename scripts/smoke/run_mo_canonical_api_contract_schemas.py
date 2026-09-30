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
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.main import app  # noqa: E402
from nex_mo.remote_provider import reset_remote_provider_telemetry  # noqa: E402
from nex_runtime import issue_mock_service_token  # noqa: E402


SCHEMA_ROOT = ROOT / "contracts" / "schemas" / "service" / "nex_mo"
FORBIDDEN_PUBLIC_FIELDS = ("provider_endpoint", "api_key", "model_path")


def run_mo_canonical_api_contract_schemas(root: Path = ROOT) -> dict[str, Any]:
    schema_root = root / "contracts" / "schemas" / "service" / "nex_mo"
    token = issue_mock_service_token(service_id="nex-cx", audience="nex-mo")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-s114-schema-evidence",
        "traceparent": (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-"
            "00f067aa0ba902b7-01"
        ),
    }
    surfaces = (
        ("provider_routes", "GET", "/api/v1/provider-routes", None, "provider_route_list.v1.schema.json"),
        ("model_profiles", "GET", "/api/v1/provider-profiles", None, "model_profile_list.v1.schema.json"),
        ("provider_telemetry", "GET", "/api/v1/provider-telemetry", None, "provider_telemetry_snapshot.v1.schema.json"),
        (
            "embedding",
            "POST",
            "/api/v1/embeddings",
            {"inputs": ["contract evidence"]},
            "embedding_response.v1.schema.json",
        ),
        (
            "rerank",
            "POST",
            "/api/v1/rerank",
            {"query": "contract", "documents": ["evidence", "other"]},
            "rerank_response.v1.schema.json",
        ),
        (
            "generation",
            "POST",
            "/api/v1/generations",
            {"prompt": "Summarize contract evidence."},
            "generation_response.v1.schema.json",
        ),
    )
    request_schemas = {
        "embedding": "embedding_request.v1.schema.json",
        "rerank": "rerank_request.v1.schema.json",
        "generation": "generation_request.v1.schema.json",
    }
    results: list[dict[str, Any]] = []
    reset_remote_provider_telemetry()
    try:
        with patch.dict(os.environ, {"NEX_MO_PROVIDER_MODE": "mock"}, clear=False):
            client = TestClient(app)
            for name, method, path, payload, response_schema in surfaces:
                request_valid = True
                if payload is not None:
                    request_valid = _validates(
                        schema_root / request_schemas[name],
                        payload,
                    )
                response = client.request(method, path, headers=headers, json=payload)
                response_payload = response.json()
                results.append(
                    {
                        "name": name,
                        "http_status": response.status_code,
                        "request_valid": request_valid,
                        "response_valid": _validates(
                            schema_root / response_schema,
                            response_payload,
                        ),
                        "private_fields_absent": not _contains_forbidden_key(
                            response_payload
                        ),
                    }
                )
    except Exception as exc:
        return _failed_evidence(results, exc)
    finally:
        reset_remote_provider_telemetry()

    checks = {
        "six_runtime_surfaces_checked": len(results) == 6,
        "all_requests_canonical": all(item["request_valid"] for item in results),
        "all_responses_successful": all(item["http_status"] == 200 for item in results),
        "all_responses_canonical": all(item["response_valid"] for item in results),
        "private_fields_absent": all(item["private_fields_absent"] for item in results),
        "nine_canonical_schemas_present": len(tuple(schema_root.glob("*.json"))) >= 17,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_canonical_api_contract_schemas.v1",
        "slice": "1133",
        "requirement": "S114",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_canonical_api_contract_schemas_failed",
        "checks": checks,
        "summary": {
            "surface_count": len(results),
            "request_schema_count": len(request_schemas),
            "response_schema_count": len(results),
            "validated_surface_count": sum(
                item["http_status"] == 200
                and item["request_valid"]
                and item["response_valid"]
                and item["private_fields_absent"]
                for item in results
            ),
        },
        "surfaces": results,
        "next_slice": "1134",
    }


def _validates(path: Path, payload: Any) -> bool:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return not tuple(Draft202012Validator(schema).iter_errors(payload))


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in FORBIDDEN_PUBLIC_FIELDS
            or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _failed_evidence(results: list[dict[str, Any]], exc: Exception) -> dict[str, Any]:
    return {
        "evidence_schema_version": "mo_canonical_api_contract_schemas.v1",
        "slice": "1133",
        "requirement": "S114",
        "status": "FAIL",
        "failure_code": "mo_canonical_api_contract_schemas_failed",
        "checks": {},
        "summary": {
            "surface_count": len(results),
            "request_schema_count": 3,
            "response_schema_count": 6,
            "validated_surface_count": 0,
        },
        "surfaces": results,
        "failure_detail": exc.__class__.__name__,
        "next_slice": "blocked",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_canonical_api_contract_schemas="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"surfaces={summary.get('validated_surface_count', 0)}/"
        f"{summary.get('surface_count', 0)} "
        f"requests={summary.get('request_schema_count', 0)} "
        f"responses={summary.get('response_schema_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_canonical_api_contract_schemas()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
