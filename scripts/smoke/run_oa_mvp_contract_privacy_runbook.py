#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "scripts/quality",
    ROOT / "scripts/smoke",
    ROOT / "services/nex-oa",
):
    sys.path.insert(0, str(path))

from run_oa_signed_token_failure_audit import (  # noqa: E402
    run_oa_signed_token_failure_audit,
)
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "oa_mvp_contract_privacy_runbook_evidence.v1"
REQUIRED_SCHEMAS = (
    "auth_event_list.v1.schema.json",
    "browser_session.v1.schema.json",
    "effective_authorization_response.v1.schema.json",
    "service_principal_response.v1.schema.json",
    "signed_jwks.v1.schema.json",
    "signed_token_response.v1.schema.json",
    "token_introspection.v1.schema.json",
    "token_revocation.v1.schema.json",
)
REQUIRED_PATHS = {
    "/api/v1/auth/service-token": "post",
    "/api/v1/auth/introspect": "post",
    "/api/v1/auth/revoke": "post",
    "/.well-known/jwks.json": "get",
    "/internal/v1/auth/tenants/{tenant_id}/subjects/{subject_id}/authorization": "get",
    "/internal/v1/auth/security-events": "get",
}
SENSITIVE_ROUTE_SCOPES = {
    "/api/v1/auth/introspect": "token:introspect",
    "/api/v1/auth/revoke": "token:revoke",
}
RUNBOOK_MARKERS = (
    "## Preconditions",
    "## Execution Order",
    "## Expected Evidence",
    "## Failure Response",
    "## Key Rollback",
    "## Revocation Response",
    "## Privacy Controls",
    "## Deferred Deployment Controls",
    "SIGNED_ONLY must remain enabled during rollback",
    "never enable a mock token fallback",
    "run_quality_gate.sh",
)
S130_DOCUMENTS = tuple(
    f"docs/slices/{name}"
    for name in (
        "1292_oa_mvp_acceptance_platform_trust_boundary.md",
        "1293_oa_signed_token_failure_audit_hardening.md",
        "1294_oa_mvp_acceptance_policy_traceability.md",
        "1295_oa_identity_session_authorization_restart_smoke.md",
        "1296_oa_signing_key_rotation_restart_smoke.md",
        "1297_oa_revocation_introspection_restart_smoke.md",
        "1298_oa_cross_service_signed_only_trust_smoke.md",
        "1299_oa_mvp_acceptance_contract_privacy_runbook.md",
    )
)
FORBIDDEN_EVIDENCE_FRAGMENTS = (
    "Bearer eyJ",
    '"access_token":',
    '"client_secret":',
    '"raw_jti":',
    "-----BEGIN PRIVATE KEY-----",
    "api-key=",
)


def run_oa_mvp_contract_privacy_runbook(
    root: Path = ROOT,
) -> dict[str, Any]:
    contracts = validate_contract_tree(root / "contracts")
    openapi = _yaml(root / "contracts/openapi/nex-oa.openapi.yaml")
    paths = _mapping(openapi.get("paths"))
    schema_root = root / "contracts/schemas/service/nex_oa"
    schemas = {
        name: _json(schema_root / name) for name in REQUIRED_SCHEMAS
    }
    auth_event_schema = schemas["auth_event_list.v1.schema.json"]
    runbook_path = root / "docs/runbooks/oa_mvp_platform_trust_operations.md"
    runbook = _text(runbook_path)
    documents = {name: _text(root / name) for name in S130_DOCUMENTS}
    evidence_text = "\n".join((runbook, *documents.values()))
    failure_audit = run_oa_signed_token_failure_audit()

    route_checks = {
        route: method in _mapping(paths.get(route))
        for route, method in REQUIRED_PATHS.items()
    }
    sensitive_checks = {
        route: _sensitive_route_matches(
            paths,
            route=route,
            scope=scope,
        )
        for route, scope in SENSITIVE_ROUTE_SCOPES.items()
    }
    schema_checks = {
        name: _strict_schema(payload) for name, payload in schemas.items()
    }
    event_types = _auth_event_types(auth_event_schema)
    privacy_hits = sorted(
        fragment
        for fragment in FORBIDDEN_EVIDENCE_FRAGMENTS
        if fragment in evidence_text
    )
    runbook_missing = sorted(
        marker for marker in RUNBOOK_MARKERS if marker not in runbook
    )
    missing_documents = sorted(
        name for name, content in documents.items() if not content
    )
    checks = {
        "contract_tree_valid": contracts.ok,
        "contract_inventory_current": (
            contracts.schema_count >= 156
            and contracts.example_count >= 214
            and contracts.negative_example_count >= 184
            and contracts.openapi_count >= 7
        ),
        "required_openapi_paths_published": all(route_checks.values()),
        "sensitive_routes_signed_and_scoped": all(
            sensitive_checks.values()
        ),
        "required_schemas_strict": all(schema_checks.values()),
        "failure_event_contract_current": {
            "TOKEN_VALIDATION_FAILED",
            "SERVICE_AUTH_FAILED",
        }.issubset(event_types),
        "failure_audit_privacy_safe": (
            failure_audit.get("status") == "PASS"
            and failure_audit.get("summary", {}).get(
                "raw_material_exposure_count"
            )
            == 0
        ),
        "s130_documents_complete": not missing_documents,
        "committed_evidence_redacted": not privacy_hits,
        "runbook_complete": not runbook_missing,
        "production_deployment_not_overclaimed": (
            "Production activation still requires" in runbook
            and "must not be represented as completed" in runbook
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1299",
        "requirement": "S130",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "oa_mvp_contract_privacy_runbook_failed"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "contract_counts": {
            "schemas": contracts.schema_count,
            "examples": contracts.example_count,
            "negative_examples": contracts.negative_example_count,
            "openapi": contracts.openapi_count,
        },
        "route_checks": route_checks,
        "sensitive_route_checks": sensitive_checks,
        "schema_checks": schema_checks,
        "failure_audit_summary": failure_audit.get("summary", {}),
        "missing_documents": missing_documents,
        "privacy_hits": privacy_hits,
        "runbook_missing": runbook_missing,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "route_count": len(route_checks),
            "strict_schema_count": sum(schema_checks.values()),
            "document_count": len(documents) + 1,
            "privacy_violation_count": len(privacy_hits),
        },
        "next_slice": "1300" if passed else "blocked",
    }


def _sensitive_route_matches(
    paths: Mapping[str, Any],
    *,
    route: str,
    scope: str,
) -> bool:
    operation = _mapping(_mapping(paths.get(route)).get("post"))
    security = operation.get("security")
    return (
        isinstance(security, list)
        and {"signedServiceBearer": []} in security
        and scope in operation.get("x-nex-required-scopes", [])
    )


def _strict_schema(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("type") == "object"
        and payload.get("additionalProperties") is False
        and isinstance(payload.get("required"), list)
        and bool(payload["required"])
    )


def _auth_event_types(payload: Mapping[str, Any]) -> set[str]:
    definitions = _mapping(payload.get("$defs"))
    event = _mapping(definitions.get("auth_event"))
    properties = _mapping(event.get("properties"))
    event_type = _mapping(properties.get("event_type"))
    values = event_type.get("enum")
    return {str(item) for item in values} if isinstance(values, list) else set()


def _yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    contracts = evidence.get("contract_counts") or {}
    return (
        "oa_mvp_contract_privacy_runbook="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"schemas={contracts.get('schemas', 0)} "
        f"routes={summary.get('route_count', 0)} "
        f"documents={summary.get('document_count', 0)} "
        f"privacy={summary.get('privacy_violation_count', 1)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_mvp_contract_privacy_runbook()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
