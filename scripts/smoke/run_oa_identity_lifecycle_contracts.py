#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from nex_oa.contract_api_drift_audit import (  # noqa: E402
    build_oa_contract_api_drift_audit,
)
from nex_oa.identity_lifecycle_audit import (  # noqa: E402
    build_oa_identity_lifecycle_audit,
)


SCHEMA_PATHS = {
    "subject": "contracts/schemas/service/nex_oa/subject_lifecycle_response.v1.schema.json",
    "membership": "contracts/schemas/service/nex_oa/membership_lifecycle_response.v1.schema.json",
}
POSITIVE_PATHS = {
    "subject": "contracts/examples/auth/oa_subject_lifecycle_response.disabled.json",
    "membership": "contracts/examples/auth/oa_membership_lifecycle_response.disabled.json",
}
NEGATIVE_PATHS = {
    "subject": "contracts/tests/negative/auth/oa_subject_lifecycle_response.password_leak.json",
    "membership": "contracts/tests/negative/auth/oa_membership_lifecycle_response.token_leak.json",
}
LIFECYCLE_OPERATIONS = (
    "/internal/v1/identity/tenants/{tenant_id}/subjects/{subject_id}/lifecycle",
    "/internal/v1/identity/tenants/{tenant_id}/memberships/{subject_id}/lifecycle",
)
REQUIRED_SCOPES = ["service:call", "identity:lifecycle:write"]
FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "credential_hash",
        "password",
        "password_hash",
        "refresh_token",
        "service_token",
    }
)


def run_oa_identity_lifecycle_contracts(root: Path = ROOT) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    schemas = {
        name: _load_json(root / relative, issues, name=f"{name}_schema")
        for name, relative in SCHEMA_PATHS.items()
    }
    positives = {
        name: _load_json(root / relative, issues, name=f"{name}_positive")
        for name, relative in POSITIVE_PATHS.items()
    }
    negatives = {
        name: _load_json(root / relative, issues, name=f"{name}_negative")
        for name, relative in NEGATIVE_PATHS.items()
    }
    schema_checks = {
        name: _schema_valid(schema) for name, schema in schemas.items()
    }
    positive_checks = {
        name: _payload_valid(schemas.get(name), payload)
        for name, payload in positives.items()
    }
    negative_checks = {
        name: _payload_rejected(schemas.get(name), payload)
        for name, payload in negatives.items()
    }

    openapi = _load_yaml(
        root / "contracts/openapi/nex-oa.openapi.yaml",
        issues,
        name="oa_openapi",
    )
    operations = [_operation(openapi, path) for path in LIFECYCLE_OPERATIONS]
    lifecycle_audit = _safe_audit(build_oa_identity_lifecycle_audit, root)
    drift_audit = _safe_audit(build_oa_contract_api_drift_audit, root)
    lifecycle_summary = _mapping(lifecycle_audit.get("summary"))
    drift_summary = _mapping(drift_audit.get("summary"))

    checks = {
        "inputs_present": not issues,
        "schemas_valid": all(schema_checks.values()),
        "positive_fixtures_valid": all(positive_checks.values()),
        "negative_privacy_fixtures_rejected": all(negative_checks.values()),
        "positive_fixtures_privacy_safe": all(
            not _contains_forbidden_key(payload) for payload in positives.values()
        ),
        "lifecycle_operations_documented": all(bool(item) for item in operations),
        "service_bearer_required": all(
            {"serviceBearer": []} in list(item.get("security") or [])
            for item in operations
            if item
        )
        and len([item for item in operations if item]) == len(LIFECYCLE_OPERATIONS),
        "dedicated_scopes_declared": all(
            item.get("x-nex-required-scopes") == REQUIRED_SCOPES
            for item in operations
            if item
        )
        and len([item for item in operations if item]) == len(LIFECYCLE_OPERATIONS),
        "canonical_schema_links_declared": _canonical_links_present(openapi),
        "lifecycle_audit_rebaselined": (
            lifecycle_audit.get("status") == "PASS"
            and lifecycle_summary.get("implemented_count") == 6
            and lifecycle_summary.get("gap_count") == 2
        ),
        "contract_drift_reduced": (
            drift_audit.get("status") == "PASS"
            and drift_summary.get("openapi_operation_count") == 8
            and drift_summary.get("drift_count") == 23
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks and not issues else "FAIL"
    return {
        "evidence_schema_version": "oa_identity_lifecycle_contracts_evidence.v1",
        "slice": "1219",
        "requirement": "S122",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "oa_identity_lifecycle_contracts_failed"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "schema_count": len(schemas),
            "positive_fixture_count": sum(positive_checks.values()),
            "negative_fixture_count": sum(negative_checks.values()),
            "documented_operation_count": sum(bool(item) for item in operations),
            "lifecycle_implemented_count": lifecycle_summary.get(
                "implemented_count", 0
            ),
            "remaining_lifecycle_gap_count": lifecycle_summary.get("gap_count", 0),
            "remaining_contract_drift_count": drift_summary.get("drift_count", 0),
            "issue_count": len(issues),
        },
        "issues": issues,
    }


def _load_json(
    path: Path, issues: list[dict[str, Any]], *, name: str
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append({"category": "input_invalid", "name": name, "detail": type(exc).__name__})
        return {}
    if not isinstance(payload, dict):
        issues.append({"category": "input_invalid", "name": name, "detail": "not_object"})
        return {}
    return payload


def _load_yaml(
    path: Path, issues: list[dict[str, Any]], *, name: str
) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        issues.append({"category": "input_invalid", "name": name, "detail": type(exc).__name__})
        return {}
    if not isinstance(payload, dict):
        issues.append({"category": "input_invalid", "name": name, "detail": "not_object"})
        return {}
    return payload


def _schema_valid(schema: Mapping[str, Any] | None) -> bool:
    if not schema:
        return False
    try:
        Draft202012Validator.check_schema(dict(schema))
    except Exception:
        return False
    return True


def _payload_valid(
    schema: Mapping[str, Any] | None, payload: Mapping[str, Any] | None
) -> bool:
    if not schema or not payload:
        return False
    try:
        Draft202012Validator(dict(schema)).validate(dict(payload))
    except Exception:
        return False
    return True


def _payload_rejected(
    schema: Mapping[str, Any] | None, payload: Mapping[str, Any] | None
) -> bool:
    if not schema or not payload:
        return False
    try:
        Draft202012Validator(dict(schema)).validate(dict(payload))
    except ValidationError:
        return True
    except Exception:
        return False
    return False


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in FORBIDDEN_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _operation(openapi: Mapping[str, Any], path: str) -> dict[str, Any]:
    paths = _mapping(openapi.get("paths"))
    return _mapping(_mapping(paths.get(path)).get("patch"))


def _canonical_links_present(openapi: Mapping[str, Any]) -> bool:
    schemas = _mapping(_mapping(openapi.get("components")).get("schemas"))
    expected = {
        "SubjectLifecycleResponse": SCHEMA_PATHS["subject"].removeprefix("contracts/"),
        "MembershipLifecycleResponse": SCHEMA_PATHS["membership"].removeprefix(
            "contracts/"
        ),
    }
    return all(
        _mapping(schemas.get(name)).get("x-nex-canonical-json-schema") == path
        for name, path in expected.items()
    )


def _safe_audit(builder, root: Path) -> dict[str, Any]:
    try:
        result = builder(root)
    except Exception as exc:
        return {"status": "FAIL", "failure_code": type(exc).__name__}
    return dict(result) if isinstance(result, Mapping) else {"status": "FAIL"}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "oa_identity_lifecycle_contracts="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"schemas={summary.get('schema_count', 0)} "
        f"operations={summary.get('documented_operation_count', 0)} "
        f"lifecycle_gaps={summary.get('remaining_lifecycle_gap_count', 0)} "
        f"contract_drift={summary.get('remaining_contract_drift_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_identity_lifecycle_contracts()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
