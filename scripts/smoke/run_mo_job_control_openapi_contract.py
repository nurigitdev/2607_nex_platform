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
    _runtime_operations,
    build_mo_contract_api_drift_audit,
)


JOB_OPERATIONS = {
    "GET /internal/v1/jobs/{job_id}": "getMoServiceJob",
    "POST /internal/v1/jobs/{job_id}/cancel": "cancelMoServiceJob",
    "POST /internal/v1/jobs/{job_id}/retry": "retryMoServiceJob",
    "POST /internal/v1/jobs/{job_id}/replay": "replayMoServiceJob",
}


def run_mo_job_control_openapi_contract(
    root: Path = ROOT,
    *,
    document: Mapping[str, Any] | None = None,
    runtime_operations: set[str] | None = None,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(document) if document is not None else _read_openapi(root)
    runtime = runtime_operations if runtime_operations is not None else _runtime_operations()
    drift = dict(audit) if audit is not None else build_mo_contract_api_drift_audit(root)
    paths = _mapping(payload.get("paths"))
    results = []
    for operation_key, operation_id in JOB_OPERATIONS.items():
        method, path = operation_key.split(" ", 1)
        operation = _mapping(_mapping(paths.get(path)).get(method.lower()))
        responses = _mapping(operation.get("responses"))
        results.append(
            {
                "operation": operation_key,
                "runtime_present": operation_key in runtime,
                "operation_id_matches": operation.get("operationId") == operation_id,
                "security_present": operation.get("security") == [{"serviceBearer": []}],
                "job_id_parameter_present": bool(operation.get("parameters")),
                "request_body_present": (
                    bool(_mapping(operation.get("requestBody")))
                    if method == "POST"
                    else True
                ),
                "success_schema_present": bool(
                    _mapping(_mapping(responses.get("200")).get("content"))
                ),
                "auth_failure_documented": "401" in responses,
                "not_found_documented": "404" in responses,
            }
        )
    summary = _mapping(drift.get("summary"))
    missing = set(drift.get("missing_openapi_operations") or ())
    checks = {
        "four_job_operations_documented": len(results) == 4,
        "runtime_operations_present": all(item["runtime_present"] for item in results),
        "operation_ids_match": all(item["operation_id_matches"] for item in results),
        "service_security_complete": all(item["security_present"] for item in results),
        "path_parameters_complete": all(
            item["job_id_parameter_present"] for item in results
        ),
        "action_request_bodies_complete": all(
            item["request_body_present"] for item in results
        ),
        "success_schemas_complete": all(
            item["success_schema_present"] for item in results
        ),
        "standard_failures_documented": all(
            item["auth_failure_documented"] and item["not_found_documented"]
            for item in results
        ),
        "job_operations_removed_from_drift": not (set(JOB_OPERATIONS) & missing),
        "remaining_drift_count_expected": _count(summary, "drift_count") == 4,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_job_control_openapi_contract.v1",
        "slice": "1136",
        "requirement": "S114",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_job_control_openapi_contract_failed",
        "checks": checks,
        "summary": {
            "operation_count": len(results),
            "documented_operation_count": sum(
                all(
                    item[key]
                    for key in (
                        "runtime_present",
                        "operation_id_matches",
                        "security_present",
                        "job_id_parameter_present",
                        "request_body_present",
                        "success_schema_present",
                        "auth_failure_documented",
                        "not_found_documented",
                    )
                )
                for item in results
            ),
            "remaining_drift_count": _count(summary, "drift_count"),
        },
        "operations": results,
        "next_slice": "1137" if passed else "blocked",
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
        "mo_job_control_openapi_contract="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"operations={summary.get('documented_operation_count', 0)}/"
        f"{summary.get('operation_count', 0)} "
        f"remaining={summary.get('remaining_drift_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_job_control_openapi_contract()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
