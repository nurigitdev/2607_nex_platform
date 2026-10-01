from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from nex_oa.identity_lifecycle import OaIdentityLifecycleError
from nex_oa.identity_lifecycle_repository import InMemoryOaIdentityLifecycleRepository
from nex_oa.identity_lifecycle_service import (
    OA_IDENTITY_LIFECYCLE_WRITE_SCOPE,
    OaIdentityLifecycleService,
    _normalize_subject_transition_payload,
    register_identity_lifecycle_routes,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_oa.subjects import InMemoryOaSubjectRegistry, SubjectRegistryError
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


def _service_and_client():
    subjects = InMemoryOaSubjectRegistry()
    subjects.ensure_subject({"tenant_id": "tenant-a", "subject_id": "employee-a"})
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    repository = InMemoryOaIdentityLifecycleRepository(subjects, memberships)
    service = OaIdentityLifecycleService(subjects, repository)
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_identity_lifecycle_routes(app, service=service)
    return service, repository, TestClient(app)


def _headers(*, lifecycle_scope: bool = True) -> dict[str, str]:
    scopes = [DEFAULT_SERVICE_SCOPE]
    if lifecycle_scope:
        scopes.append(OA_IDENTITY_LIFECYCLE_WRITE_SCOPE)
    issued = issue_mock_service_token(
        service_id="nex-ag", audience="nex-oa", scopes=scopes
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "request-1216",
        "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
    }


def test_service_transitions_subject_and_records_server_actor() -> None:
    service, repository, _ = _service_and_client()
    result = service.transition_subject(
        tenant_id="tenant-a",
        subject_id="employee-a",
        payload={
            "target_status": "DISABLED",
            "expected_revision": 1,
            "reason_code": "admin.disable",
        },
        context={
            "actor_ref_type": "nex.service",
            "actor_ref_id": "nex-ag",
            "request_id": "request-1216",
            "trace_id": "1234567890abcdef1234567890abcdef",
        },
    )

    assert result["response_schema_version"] == "oa_subject_lifecycle_response.v1"
    assert result["status"] == "DISABLED"
    assert result["revision"] == 2
    assert repository.events[0]["actor_ref_id"] == "nex-ag"


def test_service_reports_missing_subject() -> None:
    service, _, _ = _service_and_client()
    with pytest.raises(OaIdentityLifecycleError) as caught:
        service.transition_subject(
            tenant_id="tenant-a",
            subject_id="missing",
            payload={"target_status": "ACTIVE", "expected_revision": 1},
            context={},
        )
    assert caught.value.status_code == 404


def test_service_maps_subject_registry_failure() -> None:
    class FailingRegistry:
        def get_subject(self, **_kwargs):
            raise SubjectRegistryError(
                status_code=503,
                error_code="oa.subject_registry_unavailable",
                detail="subject registry unavailable",
            )

    _, repository, _ = _service_and_client()
    service = OaIdentityLifecycleService(FailingRegistry(), repository)

    with pytest.raises(OaIdentityLifecycleError) as caught:
        service.transition_subject(
            tenant_id="tenant-a",
            subject_id="employee-a",
            payload={"target_status": "ACTIVE", "expected_revision": 1},
            context={},
        )
    assert caught.value.status_code == 503
    assert caught.value.error_code == "oa.subject_registry_unavailable"


def test_subject_lifecycle_route_enforces_dedicated_scope_and_conflict() -> None:
    _, _, client = _service_and_client()
    path = "/internal/v1/identity/tenants/tenant-a/subjects/employee-a/lifecycle"
    payload = {
        "target_status": "DISABLED",
        "expected_revision": 1,
        "reason_code": "admin.disable",
    }

    assert client.patch(path, json=payload).status_code == 401
    denied = client.patch(path, json=payload, headers=_headers(lifecycle_scope=False))
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "TOKEN_SCOPE_MISSING"

    accepted = client.patch(path, json=payload, headers=_headers())
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "DISABLED"
    assert accepted.json()["request_id"] == "request-1216"

    stale = client.patch(path, json=payload, headers=_headers())
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "oa.lifecycle_revision_conflict"


def test_route_rejects_missing_subject_and_unsafe_payload() -> None:
    _, _, client = _service_and_client()
    missing = client.patch(
        "/internal/v1/identity/tenants/tenant-a/subjects/missing/lifecycle",
        json={"target_status": "ACTIVE", "expected_revision": 1},
        headers=_headers(),
    )
    assert missing.status_code == 404

    unsafe = client.patch(
        "/internal/v1/identity/tenants/tenant-a/subjects/employee-a/lifecycle",
        json={"target_status": "DISABLED", "expected_revision": 1, "password": "x"},
        headers=_headers(),
    )
    assert unsafe.status_code == 400
    assert unsafe.json()["error_code"] == "oa.lifecycle_payload_invalid"


def test_payload_validation_requires_target_and_revision() -> None:
    for payload in ({}, {"target_status": "ACTIVE"}, {"expected_revision": 1}):
        with pytest.raises(OaIdentityLifecycleError) as caught:
            _normalize_subject_transition_payload(payload)
        assert caught.value.error_code == "oa.lifecycle_payload_invalid"
