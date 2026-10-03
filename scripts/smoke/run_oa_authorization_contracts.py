#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))

from fastapi.testclient import TestClient  # noqa: E402

from nex_oa.authorization_repository import InMemoryOaAuthorizationRepository  # noqa: E402
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver  # noqa: E402
from nex_oa.authorization_service import (  # noqa: E402
    OA_AUTHORIZATION_ADMIN_SCOPE,
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


SCHEMA_FIXTURES = (
    (
        "authorization_role_upsert.v1.schema.json",
        "oa_authorization_role_upsert.editor.json",
        "oa_authorization_role_upsert.private_metadata.json",
    ),
    (
        "authorization_group_upsert.v1.schema.json",
        "oa_authorization_group_upsert.engineering.json",
        "oa_authorization_group_upsert.password.json",
    ),
    (
        "authorization_assignment_upsert.v1.schema.json",
        "oa_authorization_assignment_upsert.active.json",
        "oa_authorization_assignment_upsert.identity_override.json",
    ),
    (
        "authorization_mutation_response.v1.schema.json",
        "oa_authorization_mutation_response.role.json",
        "oa_authorization_mutation_response.token_leak.json",
    ),
    (
        "effective_authorization_response.v1.schema.json",
        "oa_effective_authorization_response.editor.json",
        "oa_effective_authorization_response.password_leak.json",
    ),
    (
        "authorization_event_list.v1.schema.json",
        "oa_authorization_event_list.role.json",
        "oa_authorization_event_list.cookie_leak.json",
    ),
)

OPERATIONS = {
    ("put", "/internal/v1/auth/tenants/{tenant_id}/roles/{role_id}"): (
        "authorization:admin",
        "AuthorizationRoleUpsert",
        "AuthorizationMutationResponse",
    ),
    ("put", "/internal/v1/auth/tenants/{tenant_id}/groups/{group_id}"): (
        "authorization:admin",
        "AuthorizationGroupUpsert",
        "AuthorizationMutationResponse",
    ),
    (
        "put",
        "/internal/v1/auth/tenants/{tenant_id}/groups/{group_id}/members/{subject_id}",
    ): (
        "authorization:admin",
        "AuthorizationAssignmentUpsert",
        "AuthorizationMutationResponse",
    ),
    (
        "put",
        "/internal/v1/auth/tenants/{tenant_id}/groups/{group_id}/roles/{role_id}",
    ): (
        "authorization:admin",
        "AuthorizationAssignmentUpsert",
        "AuthorizationMutationResponse",
    ),
    (
        "get",
        "/internal/v1/auth/tenants/{tenant_id}/subjects/{subject_id}/authorization",
    ): ("authorization:read", None, "EffectiveAuthorizationResponse"),
    ("get", "/internal/v1/auth/tenants/{tenant_id}/authorization-events"): (
        "authorization:read",
        None,
        "AuthorizationEventList",
    ),
    ("post", "/internal/v1/subject-registry/ensure"): (
        "identity:bootstrap:write",
        None,
        None,
    ),
    ("post", "/internal/v1/identity/memberships/ensure"): (
        "identity:bootstrap:write",
        None,
        None,
    ),
}

PRIVATE_KEY_PARTS = ("password", "secret", "token", "credential", "cookie")


def _headers(scope: str) -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, scope],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-1239",
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load_json(
        ROOT / "contracts/schemas/service/nex_oa" / schema_name
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _operation_matches(
    openapi: Mapping[str, Any],
    *,
    method: str,
    path: str,
    scope: str,
    request_schema: str | None,
    response_schema: str | None,
) -> bool:
    operation = (openapi.get("paths") or {}).get(path, {}).get(method, {})
    scopes = operation.get("x-nex-required-scopes") or []
    if operation.get("security") != [{"serviceBearer": []}]:
        return False
    if scopes != [DEFAULT_SERVICE_SCOPE, scope]:
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
    if response_schema is not None:
        response_ref = (
            operation.get("responses", {})
            .get("200", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
            .get("$ref")
        )
        if response_ref != f"#/components/schemas/{response_schema}":
            return False
    return True


def _private_paths(value: object, prefix: str = "payload") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            path = f"{prefix}.{key}"
            if any(part in str(key).lower() for part in PRIVATE_KEY_PARTS):
                paths.append(path)
            paths.extend(_private_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_private_paths(nested, f"{prefix}[{index}]"))
    return paths


def _runtime_responses() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    memberships = InMemoryOaTenantMembershipRegistry()
    memberships.ensure_membership(
        {"tenant_id": "tenant-a", "subject_id": "user-a"}
    )
    repository = InMemoryOaAuthorizationRepository()
    resolver = OaEffectiveAuthorizationResolver(repository)
    service = OaAuthorizationService(repository, resolver, memberships)
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_authorization_routes(app, service=service)
    client = TestClient(app)
    admin = _headers(OA_AUTHORIZATION_ADMIN_SCOPE)
    reader = _headers(OA_AUTHORIZATION_READ_SCOPE)
    base = "/internal/v1/auth/tenants/tenant-a"
    responses = [
        client.put(
            f"{base}/roles/editor",
            json={"scopes": ["document:read"], "expected_revision": 0},
            headers=admin,
        ),
        client.put(
            f"{base}/groups/engineering",
            json={"expected_revision": 0},
            headers=admin,
        ),
        client.put(
            f"{base}/groups/engineering/members/user-a",
            json={"expected_revision": 0},
            headers=admin,
        ),
        client.put(
            f"{base}/groups/engineering/roles/editor",
            json={"expected_revision": 0},
            headers=admin,
        ),
    ]
    effective = client.get(
        f"{base}/subjects/user-a/authorization", headers=reader
    )
    events = client.get(f"{base}/authorization-events", headers=reader)
    assert all(response.status_code == 200 for response in [*responses, effective, events])
    return [response.json() for response in responses], effective.json(), events.json()


def _fixture_validation() -> tuple[int, int, list[dict[str, Any]]]:
    positive_root = ROOT / "contracts/examples/auth"
    negative_root = ROOT / "contracts/tests/negative/auth"
    positive_valid = 0
    negative_rejected = 0
    positive_payloads: list[dict[str, Any]] = []
    for schema_name, positive_name, negative_name in SCHEMA_FIXTURES:
        validator = _validator(schema_name)
        positive = _load_json(positive_root / positive_name)
        negative = _load_json(negative_root / negative_name)
        if not list(validator.iter_errors(positive)):
            positive_valid += 1
        if list(validator.iter_errors(negative)):
            negative_rejected += 1
        positive_payloads.append(positive)
    return positive_valid, negative_rejected, positive_payloads


def run_oa_authorization_contracts() -> dict[str, Any]:
    positive_valid, negative_rejected, positive_payloads = _fixture_validation()

    openapi = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-oa.openapi.yaml").read_text(encoding="utf-8")
    )
    operation_valid = sum(
        _operation_matches(
            openapi,
            method=method,
            path=path,
            scope=config[0],
            request_schema=config[1],
            response_schema=config[2],
        )
        for (method, path), config in OPERATIONS.items()
    )
    components = openapi.get("components", {}).get("schemas", {})
    canonical_links = {
        value.get("x-nex-canonical-json-schema")
        for value in components.values()
        if isinstance(value, Mapping) and value.get("x-nex-canonical-json-schema")
    }
    expected_links = {
        f"schemas/service/nex_oa/{item[0]}" for item in SCHEMA_FIXTURES
    }

    mutations, effective, events = _runtime_responses()
    mutation_validator = _validator("authorization_mutation_response.v1.schema.json")
    effective_validator = _validator("effective_authorization_response.v1.schema.json")
    event_validator = _validator("authorization_event_list.v1.schema.json")
    runtime_valid = all(
        not list(mutation_validator.iter_errors(item)) for item in mutations
    ) and not list(effective_validator.iter_errors(effective)) and not list(
        event_validator.iter_errors(events)
    )
    privacy_paths = _private_paths([*positive_payloads, *mutations, effective, events])
    checks = {
        "positive_fixtures_valid": positive_valid == len(SCHEMA_FIXTURES),
        "negative_fixtures_rejected": negative_rejected == len(SCHEMA_FIXTURES),
        "openapi_operations_strict": operation_valid == len(OPERATIONS),
        "canonical_schema_links_complete": expected_links <= canonical_links,
        "runtime_responses_validate": runtime_valid,
        "positive_and_runtime_payloads_private_safe": not privacy_paths,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "oa_authorization_contracts_evidence.v1",
        "slice": "1239",
        "requirement": "S124",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_authorization_contracts_failed",
        "checks": checks,
        "privacy_paths": privacy_paths,
        "summary": {
            "schema_count": len(SCHEMA_FIXTURES),
            "positive_valid_count": positive_valid,
            "negative_rejected_count": negative_rejected,
            "operation_valid_count": operation_valid,
            "runtime_response_count": len(mutations) + 2,
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "oa_authorization_contracts="
        f"{'pass' if evidence.get('status') == 'PASS' else 'fail'} "
        f"schemas={summary.get('schema_count', 0)} "
        f"fixtures={summary.get('positive_valid_count', 0)}/"
        f"{summary.get('negative_rejected_count', 0)} "
        f"operations={summary.get('operation_valid_count', 0)} "
        f"runtime={summary.get('runtime_response_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_oa_authorization_contracts()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
