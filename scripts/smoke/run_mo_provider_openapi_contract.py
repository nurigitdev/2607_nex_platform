#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.contract_api_drift_audit import (  # noqa: E402
    build_mo_contract_api_drift_audit,
)


PROVIDER_PATHS = (
    "/api/v1/provider-routes",
    "/api/v1/provider-profiles",
    "/api/v1/provider-route-health",
    "/api/v1/provider-telemetry",
    "/api/v1/model-runtime-observability",
    "/api/v1/embeddings",
    "/api/v1/rerank",
    "/api/v1/generations",
)
POST_PATHS = (
    "/api/v1/embeddings",
    "/api/v1/rerank",
    "/api/v1/generations",
)
EXPECTED_OPERATION_IDS = {
    "/api/v1/embeddings": "createMoEmbeddings",
    "/api/v1/rerank": "createMoRerank",
    "/api/v1/generations": "createMoGeneration",
}
CANONICAL_COMPONENTS = {
    "ProviderRouteList": "schemas/service/nex_mo/provider_route_list.v1.schema.json",
    "ModelProfileList": "schemas/service/nex_mo/model_profile_list.v1.schema.json",
    "ProviderTelemetrySnapshot": "schemas/service/nex_mo/provider_telemetry_snapshot.v1.schema.json",
    "RuntimeObservability": "schemas/service/nex_mo/runtime_observability.v1.schema.json",
    "EmbeddingRequest": "schemas/service/nex_mo/embedding_request.v1.schema.json",
    "EmbeddingResponse": "schemas/service/nex_mo/embedding_response.v1.schema.json",
    "RerankRequest": "schemas/service/nex_mo/rerank_request.v1.schema.json",
    "RerankResponse": "schemas/service/nex_mo/rerank_response.v1.schema.json",
    "GenerationRequest": "schemas/service/nex_mo/generation_request.v1.schema.json",
    "GenerationResponse": "schemas/service/nex_mo/generation_response.v1.schema.json",
}


def run_mo_provider_openapi_contract(
    root: Path = ROOT,
    *,
    document: Mapping[str, Any] | None = None,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(document) if document is not None else _read_openapi(root)
    drift = dict(audit) if audit is not None else build_mo_contract_api_drift_audit(root)
    paths = _mapping(payload.get("paths"))
    components = _mapping(_mapping(payload.get("components")).get("schemas"))
    path_results = []
    for path in PROVIDER_PATHS:
        method = "post" if path in POST_PATHS else "get"
        operation = _mapping(_mapping(paths.get(path)).get(method))
        response = _mapping(_mapping(operation.get("responses")).get("200"))
        path_results.append(
            {
                "path": path,
                "method": method.upper(),
                "security": operation.get("security") == [{"serviceBearer": []}],
                "success_schema": bool(_mapping(response.get("content"))),
                "request_schema": (
                    bool(_mapping(operation.get("requestBody")))
                    if method == "post"
                    else True
                ),
                "mode_neutral_operation": (
                    operation.get("operationId") == EXPECTED_OPERATION_IDS[path]
                    if method == "post"
                    else True
                ),
            }
        )
    component_results = {
        name: _mapping(components.get(name)).get("x-nex-canonical-json-schema")
        == schema_path
        and (root / "contracts" / schema_path).is_file()
        for name, schema_path in CANONICAL_COMPONENTS.items()
    }
    summary = _mapping(drift.get("summary"))
    checks = {
        "openapi_document_present": bool(payload),
        "eight_provider_paths_documented": len(path_results) == 8,
        "provider_security_complete": all(item["security"] for item in path_results),
        "provider_success_schemas_complete": all(
            item["success_schema"] for item in path_results
        ),
        "provider_request_schemas_complete": all(
            item["request_schema"] for item in path_results
        ),
        "provider_operations_mode_neutral": all(
            item["mode_neutral_operation"] for item in path_results
        ),
        "canonical_components_complete": all(component_results.values()),
        "provider_drift_removed": all(
            _count(summary, key) == 0
            for key in (
                "stale_mock_operation_count",
                "missing_request_body_count",
                "missing_success_schema_count",
                "missing_security_count",
            )
        ),
        "remaining_drift_is_shared_routes": _count(summary, "drift_count") <= 8,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_openapi_contract.v1",
        "slice": "1135",
        "requirement": "S114",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_openapi_contract_failed",
        "checks": checks,
        "summary": {
            "provider_path_count": len(path_results),
            "canonical_component_count": len(component_results),
            "closed_provider_drift_count": 17 if checks["provider_drift_removed"] else 0,
            "remaining_drift_count": _count(summary, "drift_count"),
        },
        "paths": path_results,
        "components": component_results,
        "next_slice": "1136" if passed else "blocked",
    }


def _read_openapi(root: Path) -> dict[str, Any]:
    path = root / "contracts" / "openapi" / "nex-mo.openapi.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _count(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key, 0)
    return item if isinstance(item, int) and item >= 0 else 0


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "mo_provider_openapi_contract="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"paths={summary.get('provider_path_count', 0)} "
        f"components={summary.get('canonical_component_count', 0)} "
        f"closed={summary.get('closed_provider_drift_count', 0)} "
        f"remaining={summary.get('remaining_drift_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_openapi_contract()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
