#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.contract_api_drift_audit import build_oa_contract_api_drift_audit  # noqa: E402
from nex_oa.service_principal_api import register_service_principal_routes  # noqa: E402
from nex_oa.service_principal_repository import (  # noqa: E402
    InMemoryOaServicePrincipalRepository,
)
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


CONTRACTS = {
    "principal_response": (
        "service_principal_response.v1.schema.json",
        "oa_service_principal_response.active.json",
        "oa_service_principal_response.secret_hash_leak.json",
    ),
    "principal_list": (
        "service_principal_list.v1.schema.json",
        "oa_service_principal_list.active.json",
        "oa_service_principal_list.client_secret_leak.json",
    ),
    "credential_response": (
        "service_credential_response.v1.schema.json",
        "oa_service_credential_response.active.json",
        "oa_service_credential_response.secret_hash_leak.json",
    ),
    "credential_list": (
        "service_credential_list.v1.schema.json",
        "oa_service_credential_list.active.json",
        "oa_service_credential_list.client_secret_leak.json",
    ),
    "credential_issue": (
        "service_credential_issue.v1.schema.json",
        "oa_service_credential_issue.once.json",
        "oa_service_credential_issue.secret_hash_leak.json",
    ),
    "credential_rotation": (
        "service_credential_rotation.v1.schema.json",
        "oa_service_credential_rotation.once.json",
        "oa_service_credential_rotation.previous_secret_leak.json",
    ),
}
OPERATIONS = {
    ("post", "/internal/v1/service-principals"): (
        "service-principal:admin", "ServicePrincipalUpsert", "ServicePrincipalResponse"
    ),
    ("get", "/internal/v1/service-principals"): (
        "service-principal:read", None, "ServicePrincipalList"
    ),
    ("get", "/internal/v1/service-principals/{principal_id}"): (
        "service-principal:read", None, "ServicePrincipalResponse"
    ),
    ("patch", "/internal/v1/service-principals/{principal_id}/status"): (
        "service-principal:admin", "ServicePrincipalStatusTransition", "ServicePrincipalResponse"
    ),
    ("post", "/internal/v1/service-principals/{principal_id}/credentials"): (
        "service-principal:admin", "ServiceCredentialIssueRequest", "ServiceCredentialIssueResponse"
    ),
    ("get", "/internal/v1/service-principals/{principal_id}/credentials"): (
        "service-principal:read", None, "ServiceCredentialList"
    ),
    ("get", "/internal/v1/service-credentials/{credential_id}"): (
        "service-principal:read", None, "ServiceCredentialResponse"
    ),
    ("post", "/internal/v1/service-credentials/{credential_id}/rotate"): (
        "service-principal:admin", "ServiceCredentialRotationRequest", "ServiceCredentialRotationResponse"
    ),
    ("patch", "/internal/v1/service-credentials/{credential_id}/status"): (
        "service-principal:admin", "ServiceCredentialStatusTransition", "ServiceCredentialResponse"
    ),
}
CANONICAL_LINKS = {
    "ServicePrincipalResponse": "schemas/service/nex_oa/service_principal_response.v1.schema.json",
    "ServicePrincipalList": "schemas/service/nex_oa/service_principal_list.v1.schema.json",
    "ServiceCredentialResponse": "schemas/service/nex_oa/service_credential_response.v1.schema.json",
    "ServiceCredentialList": "schemas/service/nex_oa/service_credential_list.v1.schema.json",
    "ServiceCredentialIssueResponse": "schemas/service/nex_oa/service_credential_issue.v1.schema.json",
    "ServiceCredentialRotationResponse": "schemas/service/nex_oa/service_credential_rotation.v1.schema.json",
}
FORBIDDEN_KEY_PARTS = ("password", "secret_hash", "token", "authorization", "cookie")
ONE_TIME_SECRET_CONTRACTS = frozenset(("credential_issue", "credential_rotation"))


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"contract input must be an object: {path}")
    return value


def _operation_matches(
    openapi: Mapping[str, Any],
    *,
    method: str,
    path: str,
    scope: str,
    request_schema: str | None,
    response_schema: str,
) -> bool:
    operation = (openapi.get("paths") or {}).get(path, {}).get(method, {})
    if operation.get("security") != [{"serviceBearer": []}]:
        return False
    if operation.get("x-nex-required-scopes") != [DEFAULT_SERVICE_SCOPE, scope]:
        return False
    if request_schema is not None:
        request_ref = (
            operation.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
            .get("$ref")
        )
        if request_ref != f"#/components/schemas/{request_schema}":
            return False
    response_ref = (
        operation.get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref")
    )
    return response_ref == f"#/components/schemas/{response_schema}"


def _sensitive_paths(value: object, prefix: str = "payload") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            path = f"{prefix}.{key}"
            if any(part in str(key).lower() for part in FORBIDDEN_KEY_PARTS):
                paths.append(path)
            paths.extend(_sensitive_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_sensitive_paths(nested, f"{prefix}[{index}]"))
    return paths


def _privacy_safe(contract_name: str, payload: Mapping[str, Any]) -> bool:
    if _sensitive_paths(payload):
        return False
    secret_paths = _key_paths(payload, "client_secret")
    expected = ["payload.client_secret"] if contract_name in ONE_TIME_SECRET_CONTRACTS else []
    return secret_paths == expected and (
        contract_name not in ONE_TIME_SECRET_CONTRACTS
        or payload.get("secret_display") == "once"
    )


def _key_paths(value: object, target: str, prefix: str = "payload") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            path = f"{prefix}.{key}"
            if key == target:
                paths.append(path)
            paths.extend(_key_paths(nested, target, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_key_paths(nested, target, f"{prefix}[{index}]"))
    return paths


def _headers(scope: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, scope],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-1259",
        "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
    }


def _runtime_payloads() -> dict[str, dict[str, Any]]:
    repository = InMemoryOaServicePrincipalRepository()
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_service_principal_routes(
        app,
        service=OaServicePrincipalService(repository),
        audit_emitter=OperationalEventEmitter(
            service_id="nex-oa", store=InMemoryOperationalEventStore()
        ),
    )
    client = TestClient(app)
    admin = _headers("service-principal:admin")
    reader = _headers("service-principal:read")
    created = client.post(
        "/internal/v1/service-principals",
        headers=admin,
        json={
            "principal_id": "ae-runtime",
            "service_id": "nex-ae-api",
            "display_name": "AE Runtime",
            "allowed_audiences": ["nex-cx"],
            "allowed_scopes": ["document:read"],
            "expected_revision": 0,
        },
    )
    principal_list = client.get("/internal/v1/service-principals", headers=reader)
    issued = client.post(
        "/internal/v1/service-principals/ae-runtime/credentials",
        headers=admin,
        json={"lifetime_days": 30},
    )
    credential_id = issued.json()["credential"]["credential_id"]
    credential_list = client.get(
        "/internal/v1/service-principals/ae-runtime/credentials", headers=reader
    )
    credential = client.get(
        f"/internal/v1/service-credentials/{credential_id}", headers=reader
    )
    rotated = client.post(
        f"/internal/v1/service-credentials/{credential_id}/rotate",
        headers=admin,
        json={"expected_revision": 1, "lifetime_days": 30, "grace_seconds": 60},
    )
    responses = (created, principal_list, issued, credential_list, credential, rotated)
    if any(response.status_code != 200 for response in responses):
        raise RuntimeError("service-principal runtime response setup failed")
    return {
        "principal_response": created.json(),
        "principal_list": principal_list.json(),
        "credential_issue": issued.json(),
        "credential_list": credential_list.json(),
        "credential_response": credential.json(),
        "credential_rotation": rotated.json(),
    }


def run_oa_service_principal_contracts(root: Path = ROOT) -> dict[str, Any]:
    schema_root = root / "contracts/schemas/service/nex_oa"
    positive_root = root / "contracts/examples/auth"
    negative_root = root / "contracts/tests/negative/auth"
    contract_checks: dict[str, bool] = {}
    privacy_checks: dict[str, bool] = {}
    runtime_checks: dict[str, bool] = {}
    issues: list[dict[str, str]] = []
    try:
        runtime_payloads = _runtime_payloads() if root == ROOT else {}
        for name, (schema_name, positive_name, negative_name) in CONTRACTS.items():
            validator = Draft202012Validator(
                _load_json(schema_root / schema_name), format_checker=FormatChecker()
            )
            positive = _load_json(positive_root / positive_name)
            negative = _load_json(negative_root / negative_name)
            contract_checks[name] = (
                not list(validator.iter_errors(positive))
                and bool(list(validator.iter_errors(negative)))
            )
            privacy_checks[name] = _privacy_safe(name, positive)
            if runtime_payloads:
                runtime = runtime_payloads[name]
                runtime_checks[name] = (
                    not list(validator.iter_errors(runtime))
                    and _privacy_safe(name, runtime)
                )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        issues.append({"category": "contract_input_invalid", "detail": str(exc)})

    try:
        openapi = yaml.safe_load(
            (root / "contracts/openapi/nex-oa.openapi.yaml").read_text(encoding="utf-8")
        )
        if not isinstance(openapi, dict):
            raise ValueError("OpenAPI root must be an object")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        issues.append({"category": "openapi_invalid", "detail": str(exc)})
        openapi = {}
    operation_checks = {
        f"{method.upper()} {path}": _operation_matches(
            openapi,
            method=method,
            path=path,
            scope=scope,
            request_schema=request_schema,
            response_schema=response_schema,
        )
        for (method, path), (scope, request_schema, response_schema) in OPERATIONS.items()
    }
    schemas = ((openapi.get("components") or {}).get("schemas") or {})
    canonical_checks = {
        name: isinstance(schemas.get(name), Mapping)
        and schemas[name].get("x-nex-canonical-json-schema") == path
        for name, path in CANONICAL_LINKS.items()
    }
    drift = build_oa_contract_api_drift_audit(root)
    drift_summary = drift.get("summary") or {}
    checks = {
        "inputs_valid": not issues,
        "positive_and_negative_contracts": all(contract_checks.values()),
        "positive_fixtures_privacy_safe": all(privacy_checks.values()),
        "runtime_responses_contract_safe": bool(runtime_checks)
        and all(runtime_checks.values()),
        "operations_protected_and_scoped": all(operation_checks.values()),
        "canonical_schema_links_declared": all(canonical_checks.values()),
        "contract_inventory_complete": (
            drift.get("status") == "PASS"
            and drift_summary.get("runtime_operation_count") == 53
            and drift_summary.get("openapi_operation_count") == 30
            and drift_summary.get("schema_count") == 23
            and drift_summary.get("positive_fixture_covered_count") == 23
            and drift_summary.get("negative_fixture_covered_count") == 23
            and drift_summary.get("drift_count") == 23
        ),
    }
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    return {
        "evidence_schema_version": "oa_service_principal_contracts_evidence.v1",
        "slice": "1259",
        "requirement": "S126",
        "status": status,
        "failure_code": None if status == "PASS" else "oa_service_principal_contracts_failed",
        "checks": checks,
        "contract_checks": contract_checks,
        "privacy_checks": privacy_checks,
        "runtime_checks": runtime_checks,
        "operation_checks": operation_checks,
        "canonical_checks": canonical_checks,
        "issues": issues,
        "summary": {
            "schema_count": len(CONTRACTS),
            "positive_valid_count": sum(contract_checks.values()),
            "privacy_safe_count": sum(privacy_checks.values()),
            "runtime_valid_count": sum(runtime_checks.values()),
            "operation_valid_count": sum(operation_checks.values()),
            "remaining_contract_drift_count": drift_summary.get("drift_count", 0),
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        f"oa_service_principal_contracts={str(evidence.get('status')).lower()} "
        f"contracts={summary.get('positive_valid_count', 0)}/{summary.get('schema_count', 0)} "
        f"privacy={summary.get('privacy_safe_count', 0)}/{summary.get('schema_count', 0)} "
        f"runtime={summary.get('runtime_valid_count', 0)}/{summary.get('schema_count', 0)} "
        f"operations={summary.get('operation_valid_count', 0)}/{len(OPERATIONS)} "
        f"drift={summary.get('remaining_contract_drift_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_service_principal_contracts()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
