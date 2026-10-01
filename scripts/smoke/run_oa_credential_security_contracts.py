#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.contract_api_drift_audit import build_oa_contract_api_drift_audit  # noqa: E402
from nex_oa.credential_session_security_audit import (  # noqa: E402
    build_oa_credential_session_security_audit,
)


CONTRACTS = {
    "credential_rotation": (
        "contracts/schemas/service/nex_oa/credential_rotation.v1.schema.json",
        "contracts/examples/auth/oa_credential_rotation.password_changed.json",
        "contracts/tests/negative/auth/oa_credential_rotation.password_hash_leak.json",
    ),
    "auth_event_list": (
        "contracts/schemas/service/nex_oa/auth_event_list.v1.schema.json",
        "contracts/examples/auth/oa_auth_event_list.login.json",
        "contracts/tests/negative/auth/oa_auth_event_list.session_id_leak.json",
    ),
}
OPERATIONS = {
    ("post", "/internal/v1/auth/local-credentials/change-password"): [
        "service:call",
        "credential:security:write",
    ],
    ("post", "/internal/v1/auth/local-credentials/reset-password"): [
        "service:call",
        "credential:security:write",
    ],
    ("get", "/internal/v1/auth/security-events"): [
        "service:call",
        "credential:security:read",
    ],
}
FORBIDDEN_KEYS = frozenset(
    {"password", "password_hash", "session_id", "authorization", "cookie", "token"}
)


def run_oa_credential_security_contracts(root: Path = ROOT) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    contract_checks: dict[str, bool] = {}
    privacy_checks: dict[str, bool] = {}
    for name, (schema_path, positive_path, negative_path) in CONTRACTS.items():
        schema = _load_json(root / schema_path, issues, name=f"{name}_schema")
        positive = _load_json(root / positive_path, issues, name=f"{name}_positive")
        negative = _load_json(root / negative_path, issues, name=f"{name}_negative")
        contract_checks[name] = _valid(schema, positive) and _invalid(schema, negative)
        privacy_checks[name] = not _contains_forbidden_key(positive)

    openapi = _load_yaml(root / "contracts/openapi/nex-oa.openapi.yaml", issues)
    operation_checks = {
        f"{method.upper()} {path}": _operation_matches(
            openapi, method=method, path=path, scopes=scopes
        )
        for (method, path), scopes in OPERATIONS.items()
    }
    canonical_links = _canonical_links(openapi)
    drift = build_oa_contract_api_drift_audit(root)
    security = build_oa_credential_session_security_audit(root)
    drift_summary = drift.get("summary") or {}
    security_summary = security.get("summary") or {}
    checks = {
        "inputs_present": not issues,
        "positive_and_negative_contracts": all(contract_checks.values()),
        "positive_fixtures_privacy_safe": all(privacy_checks.values()),
        "operations_protected_and_scoped": all(operation_checks.values()),
        "canonical_schema_links_declared": canonical_links,
        "contract_drift_reduced": (
            drift.get("status") == "PASS"
            and drift_summary.get("openapi_operation_count") == 11
            and drift_summary.get("drift_count") == 23
        ),
        "security_controls_hardened": (
            security.get("status") == "PASS"
            and security_summary.get("implemented_count") == 8
            and security_summary.get("gap_count") == 0
        ),
    }
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    return {
        "evidence_schema_version": "oa_credential_security_contracts_evidence.v1",
        "slice": "1229",
        "requirement": "S123",
        "status": status,
        "failure_code": None if status == "PASS" else "oa_credential_security_contracts_failed",
        "checks": checks,
        "contract_checks": contract_checks,
        "privacy_checks": privacy_checks,
        "operation_checks": operation_checks,
        "issues": issues,
        "summary": {
            "schema_count": len(CONTRACTS),
            "documented_operation_count": sum(operation_checks.values()),
            "security_implemented_count": security_summary.get("implemented_count", 0),
            "security_gap_count": security_summary.get("gap_count", 0),
            "remaining_contract_drift_count": drift_summary.get("drift_count", 0),
        },
    }


def _load_json(path: Path, issues: list[dict[str, str]], *, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        issues.append({"category": "input_invalid", "name": name, "path": str(path)})
        return {}
    if not isinstance(value, dict):
        issues.append({"category": "input_invalid", "name": name, "path": str(path)})
        return {}
    return value


def _load_yaml(path: Path, issues: list[dict[str, str]]) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        issues.append({"category": "input_invalid", "name": "openapi", "path": str(path)})
        return {}
    if not isinstance(value, dict):
        issues.append({"category": "input_invalid", "name": "openapi", "path": str(path)})
        return {}
    return value


def _valid(schema: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    except (ValidationError, TypeError):
        return False
    return True


def _invalid(schema: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    return not _valid(schema, payload)


def _operation_matches(
    openapi: Mapping[str, Any], *, method: str, path: str, scopes: list[str]
) -> bool:
    paths = openapi.get("paths") if isinstance(openapi.get("paths"), Mapping) else {}
    item = paths.get(path) if isinstance(paths, Mapping) else None
    operation = item.get(method) if isinstance(item, Mapping) else None
    return (
        isinstance(operation, Mapping)
        and {"serviceBearer": []} in list(operation.get("security") or [])
        and operation.get("x-nex-required-scopes") == scopes
    )


def _canonical_links(openapi: Mapping[str, Any]) -> bool:
    components = openapi.get("components")
    schemas = components.get("schemas") if isinstance(components, Mapping) else {}
    expected = {
        "CredentialRotationResponse": "schemas/service/nex_oa/credential_rotation.v1.schema.json",
        "AuthEventListResponse": "schemas/service/nex_oa/auth_event_list.v1.schema.json",
    }
    return isinstance(schemas, Mapping) and all(
        isinstance(schemas.get(name), Mapping)
        and schemas[name].get("x-nex-canonical-json-schema") == path
        for name, path in expected.items()
    )


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in FORBIDDEN_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        f"oa_credential_security_contracts={str(evidence.get('status')).lower()} "
        f"schemas={summary.get('schema_count', 0)} "
        f"operations={summary.get('documented_operation_count', 0)} "
        f"security={summary.get('security_implemented_count', 0)}/8 "
        f"drift={summary.get('remaining_contract_drift_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_credential_security_contracts()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
