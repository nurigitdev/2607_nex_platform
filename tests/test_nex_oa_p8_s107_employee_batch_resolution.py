from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from nex_oa.credentials import InMemoryOaCredentialRegistry, OaCredentialError
from nex_oa.employee_batch_resolution import (
    OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
    OA_EMPLOYEE_BATCH_RESOLVE_SCOPE,
    OaEmployeeBatchResolutionError,
    OaEmployeeBatchResolver,
    _item,
    register_employee_batch_resolution_routes,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry, OaMembershipError
from nex_oa.subjects import InMemoryOaSubjectRegistry
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "tenant-p8-s107"


def _resolver() -> tuple[
    OaEmployeeBatchResolver,
    InMemoryOaCredentialRegistry,
    InMemoryOaTenantMembershipRegistry,
]:
    subjects = InMemoryOaSubjectRegistry()
    credentials = InMemoryOaCredentialRegistry(subject_registry=subjects)
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    return (
        OaEmployeeBatchResolver(
            credential_registry=credentials,
            membership_registry=memberships,
        ),
        credentials,
        memberships,
    )


def _seed(
    credentials: InMemoryOaCredentialRegistry,
    memberships: InMemoryOaTenantMembershipRegistry,
    *,
    employee_id: str,
    subject_id: str,
    display_name: str,
    tenant_id: str = TENANT,
    subject_status: str = "ACTIVE",
    membership_status: str = "ACTIVE",
) -> None:
    credentials.subject_registry.ensure_subject(
        {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "subject_display_name": display_name,
            "subject_status": subject_status,
        }
    )
    credentials.ensure_credential(
        {
            "tenant_id": tenant_id,
            "employee_id": employee_id,
            "subject_id": subject_id,
            "subject_display_name": display_name,
            "subject_status": subject_status,
            "password": "Nuri1004!",
        }
    )
    memberships.ensure_membership(
        {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "membership_status": membership_status,
        }
    )


def _candidate(index: int, employee_id: object, expected_name: object = None) -> dict:
    value = {"input_index": index, "employee_id": employee_id}
    if expected_name is not None:
        value["expected_name"] = expected_name
    return value


def _headers(*, include_scope: bool = True) -> dict[str, str]:
    scopes = [DEFAULT_SERVICE_SCOPE]
    if include_scope:
        scopes.append(OA_EMPLOYEE_BATCH_RESOLVE_SCOPE)
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-oa",
        scopes=scopes,
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def test_batch_resolution_returns_ordered_item_statuses_and_stable_evidence() -> None:
    resolver, credentials, memberships = _resolver()
    _seed(
        credentials,
        memberships,
        employee_id="EMP-001",
        subject_id="subject-001",
        display_name="홍  길동",
    )
    _seed(
        credentials,
        memberships,
        employee_id="EMP-002",
        subject_id="subject-002",
        display_name="퇴사자",
        subject_status="DISABLED",
    )
    _seed(
        credentials,
        memberships,
        employee_id="EMP-003",
        subject_id="subject-003",
        display_name="불일치 이름",
    )
    _seed(
        credentials,
        memberships,
        tenant_id="other-tenant",
        employee_id="EMP-004",
        subject_id="subject-004",
        display_name="다른 tenant",
    )
    payload = {
        "tenant_id": TENANT,
        "candidates": [
            _candidate(0, "EMP-001", " 홍 길동 "),
            _candidate(1, "emp-001"),
            _candidate(2, "bad employee"),
            _candidate(3, "EMP-404"),
            _candidate(4, "EMP-002"),
            _candidate(5, "EMP-003", "다른 이름"),
            _candidate(6, "EMP-004"),
        ],
    }

    first = resolver.resolve(payload)
    second = resolver.resolve(payload)

    assert first == second
    assert first["resolution_schema_version"] == (
        OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION
    )
    assert first["requested_count"] == 7
    assert first["resolved_count"] == 1
    assert first["rejected_count"] == 6
    assert [item["resolution_status"] for item in first["results"]] == [
        "RESOLVED",
        "DUPLICATE_INPUT",
        "INVALID_EMPLOYEE_ID",
        "EMPLOYEE_NOT_FOUND",
        "SUBJECT_INACTIVE",
        "NAME_MISMATCH",
        "EMPLOYEE_NOT_FOUND",
    ]
    resolved = first["results"][0]
    assert resolved == {
        "input_index": 0,
        "resolution_status": "RESOLVED",
        "normalized_employee_id": "emp-001",
        "subject_id": "subject-001",
        "display_name": "홍  길동",
        "subject_revision": 1,
        "tenant_membership_revision": 1,
    }
    assert "subject_id" not in first["results"][4]
    assert first["resolution_evidence_hash"] == semantic_sha256_hash_ref(
        {
            "schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
            "tenant_id": TENANT,
            "results": first["results"],
        }
    )


def test_disabled_membership_is_not_projected_as_a_resolved_identity() -> None:
    resolver, credentials, memberships = _resolver()
    _seed(
        credentials,
        memberships,
        employee_id="EMP-010",
        subject_id="subject-010",
        display_name="비활성 멤버",
        membership_status="DISABLED",
    )

    result = resolver.resolve(
        {"tenant_id": TENANT, "candidates": [_candidate(0, "EMP-010")]}
    )

    assert result["results"] == [
        {
            "input_index": 0,
            "resolution_status": "SUBJECT_INACTIVE",
            "normalized_employee_id": "emp-010",
        }
    ]


def test_missing_membership_is_tenant_safe_not_found() -> None:
    resolver, credentials, _memberships = _resolver()
    credentials.ensure_credential(
        {
            "tenant_id": TENANT,
            "employee_id": "EMP-011",
            "subject_id": "subject-011",
            "subject_display_name": "가입 전 직원",
            "password": "Nuri1004!",
        }
    )

    result = resolver.resolve(
        {"tenant_id": TENANT, "candidates": [_candidate(0, "EMP-011")]}
    )

    assert result["results"][0]["resolution_status"] == "EMPLOYEE_NOT_FOUND"
    assert "subject_id" not in result["results"][0]


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"tenant_id": TENANT, "candidates": []},
        {"tenant_id": TENANT, "candidates": "EMP-001"},
        {"tenant_id": TENANT, "candidates": [_candidate(0, "EMP-001")] * 51},
        {"tenant_id": TENANT, "candidates": ["EMP-001"]},
        {
            "tenant_id": TENANT,
            "candidates": [{**_candidate(0, "EMP-001"), "password": "secret"}],
        },
        {
            "tenant_id": TENANT,
            "candidates": [_candidate(0, "EMP-001"), _candidate(0, "EMP-002")],
        },
        {
            "tenant_id": TENANT,
            "candidates": [_candidate(True, "EMP-001")],
        },
        {
            "tenant_id": TENANT,
            "candidates": [_candidate(0, "EMP-001")],
            "unknown": True,
        },
    ),
)
def test_structurally_invalid_batch_is_rejected_before_lookup(payload: dict) -> None:
    resolver, _credentials, _memberships = _resolver()

    with pytest.raises(OaEmployeeBatchResolutionError) as raised:
        resolver.resolve(payload)

    assert raised.value.status_code == 400
    assert raised.value.error_code == "oa.employee_batch_request_invalid"
    assert raised.value.retryable is False


def test_non_mapping_request_and_defensive_unknown_status_fail_closed() -> None:
    resolver, _credentials, _memberships = _resolver()

    with pytest.raises(OaEmployeeBatchResolutionError) as request_error:
        resolver.resolve("not-an-object")  # type: ignore[arg-type]
    assert str(request_error.value) == "request must be an object"

    with pytest.raises(ValueError, match="unknown employee resolution status"):
        _item(0, "UNKNOWN")


def test_dependency_or_malformed_authority_is_operation_level_retryable_failure() -> None:
    class FailingCredentials:
        def get_credential(self, **_kwargs: Any) -> None:
            raise OaCredentialError(
                503,
                "oa.credential_registry_unavailable",
                "private database failure",
                True,
            )

    resolver = OaEmployeeBatchResolver(
        credential_registry=FailingCredentials(),  # type: ignore[arg-type]
        membership_registry=InMemoryOaTenantMembershipRegistry(),
    )
    with pytest.raises(OaEmployeeBatchResolutionError) as raised:
        resolver.resolve(
            {"tenant_id": TENANT, "candidates": [_candidate(0, "EMP-001")]}
        )
    assert raised.value.status_code == 503
    assert raised.value.retryable is True
    assert "private database failure" not in raised.value.detail

    class MalformedCredentials:
        def get_credential(self, **_kwargs: Any) -> dict:
            return {"subject_ref": "invalid"}

    malformed = OaEmployeeBatchResolver(
        credential_registry=MalformedCredentials(),  # type: ignore[arg-type]
        membership_registry=InMemoryOaTenantMembershipRegistry(),
    )
    with pytest.raises(OaEmployeeBatchResolutionError) as malformed_error:
        malformed.resolve(
            {"tenant_id": TENANT, "candidates": [_candidate(0, "EMP-001")]}
        )
    assert malformed_error.value.error_code == (
        "oa.employee_batch_resolution_unavailable"
    )


def test_membership_dependency_and_malformed_revision_are_operation_failures() -> None:
    _resolver_instance, credentials, _memberships = _resolver()
    credentials.ensure_credential(
        {
            "tenant_id": TENANT,
            "employee_id": "EMP-020",
            "subject_id": "subject-020",
            "subject_display_name": "멤버십 장애",
            "password": "Nuri1004!",
        }
    )

    class FailingMemberships:
        def get_membership(self, **_kwargs: Any) -> None:
            raise OaMembershipError(
                503,
                "oa.membership_registry_unavailable",
                "private membership failure",
                True,
            )

    unavailable = OaEmployeeBatchResolver(
        credential_registry=credentials,
        membership_registry=FailingMemberships(),  # type: ignore[arg-type]
    )
    with pytest.raises(OaEmployeeBatchResolutionError) as dependency_error:
        unavailable.resolve(
            {"tenant_id": TENANT, "candidates": [_candidate(0, "EMP-020")]}
        )
    assert dependency_error.value.status_code == 503
    assert "private membership failure" not in dependency_error.value.detail

    class AuthorityCredentials:
        def get_credential(self, **_kwargs: Any) -> dict:
            return {
                "subject_ref": {"id": "subject-020"},
                "subject_registry_snapshot": {
                    "subject": {
                        "display_name": "권위 오류",
                        "status": "ACTIVE",
                        "revision": 0,
                    }
                },
            }

    class AuthorityMemberships:
        def get_membership(self, **_kwargs: Any) -> dict:
            return {"membership": {"status": "ACTIVE", "revision": 1}}

    malformed = OaEmployeeBatchResolver(
        credential_registry=AuthorityCredentials(),  # type: ignore[arg-type]
        membership_registry=AuthorityMemberships(),  # type: ignore[arg-type]
    )
    with pytest.raises(OaEmployeeBatchResolutionError) as revision_error:
        malformed.resolve(
            {
                "tenant_id": TENANT,
                "candidates": [_candidate(0, "EMP-020")],
            }
        )
    assert revision_error.value.error_code == (
        "oa.employee_batch_resolution_unavailable"
    )

    name_mismatch = malformed.resolve(
        {
            "tenant_id": TENANT,
            "candidates": [_candidate(0, "EMP-020", expected_name=123)],
        }
    )
    assert name_mismatch["results"][0]["resolution_status"] == "NAME_MISMATCH"


def test_protected_batch_route_requires_dedicated_scope_and_maps_failures() -> None:
    resolver, credentials, memberships = _resolver()
    _seed(
        credentials,
        memberships,
        employee_id="EMP-001",
        subject_id="subject-001",
        display_name="홍길동",
    )
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_employee_batch_resolution_routes(app, resolver=resolver)
    client = TestClient(app)
    payload = {"tenant_id": TENANT, "candidates": [_candidate(0, "EMP-001")]}

    missing = client.post(
        "/internal/v1/identity/employees:resolve-batch",
        json=payload,
    )
    denied = client.post(
        "/internal/v1/identity/employees:resolve-batch",
        headers=_headers(include_scope=False),
        json=payload,
    )
    invalid = client.post(
        "/internal/v1/identity/employees:resolve-batch",
        headers=_headers(),
        json={"tenant_id": TENANT, "candidates": []},
    )
    accepted = client.post(
        "/internal/v1/identity/employees:resolve-batch",
        headers=_headers(),
        json=payload,
    )

    assert missing.status_code == 401
    assert denied.status_code == 401
    assert denied.json()["error_code"] == "TOKEN_SCOPE_MISSING"
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "oa.employee_batch_request_invalid"
    assert accepted.status_code == 200
    assert accepted.json()["resolved_count"] == 1
    assert accepted.json()["request_id"]
    assert accepted.json()["trace_id"]


def test_oa_entrypoint_registers_employee_batch_route() -> None:
    from nex_oa import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/internal/v1/identity/employees:resolve-batch" in paths
