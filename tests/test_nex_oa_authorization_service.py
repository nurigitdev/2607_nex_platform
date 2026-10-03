from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from nex_oa.authorization import OaAuthorizationError
from nex_oa.authorization_repository import (
    InMemoryOaAuthorizationRepository,
    bind_authorization_session_registry,
)
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.authorization_service import (
    OA_AUTHORIZATION_ADMIN_SCOPE,
    OA_AUTHORIZATION_READ_SCOPE,
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.memberships import (
    InMemoryOaTenantMembershipRegistry,
    OaMembershipError,
)
from nex_oa.sessions import InMemoryOaSessionRegistry
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)


CONTEXT = {
    "actor_ref": "nex.service:nex-ag",
    "request_id": "request-1237",
    "trace_id": "trace-1237",
}


def _stack():
    memberships = InMemoryOaTenantMembershipRegistry()
    memberships.ensure_membership(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "roles": ["employee"],
            "scopes": ["user:session"],
        }
    )
    repository = InMemoryOaAuthorizationRepository()
    resolver = OaEffectiveAuthorizationResolver(repository)
    sessions = InMemoryOaSessionRegistry(
        membership_registry=memberships,
        authorization_resolver=resolver,
    )
    bind_authorization_session_registry(repository, sessions)
    service = OaAuthorizationService(repository, resolver, memberships)
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_authorization_routes(app, service=service)
    return service, repository, sessions, TestClient(app)


def _headers(*scopes: str) -> dict[str, str]:
    issued = issue_mock_service_token(
        service_id="nex-ag",
        audience="nex-oa",
        scopes=[DEFAULT_SERVICE_SCOPE, *scopes],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "request-1237",
        "traceparent": (
            "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"
        ),
    }


def _seed(service: OaAuthorizationService) -> None:
    service.upsert_role(
        tenant_id="tenant-a",
        role_id="editor",
        payload={"scopes": ["document:read"], "expected_revision": 0},
        context=CONTEXT,
    )
    service.upsert_group(
        tenant_id="tenant-a",
        group_id="engineering",
        payload={"expected_revision": 0},
        context=CONTEXT,
    )
    service.upsert_group_member(
        tenant_id="tenant-a",
        group_id="engineering",
        subject_id="user-a",
        payload={"expected_revision": 0},
        context=CONTEXT,
    )


def test_service_mutations_revoke_affected_sessions() -> None:
    service, repository, sessions, _ = _stack()
    _seed(service)
    before_assignment = sessions.issue_session(
        {"tenant_id": "tenant-a", "subject_id": "user-a"}
    )

    assignment = service.upsert_group_role(
        tenant_id="tenant-a",
        group_id="engineering",
        role_id="editor",
        payload={"expected_revision": 0},
        context=CONTEXT,
    )
    assert assignment["revoked_session_count"] == 1
    assert assignment["affected_subject_ids"] == ["user-a"]
    assert (
        sessions.sessions[before_assignment["session"]["session_id"]]["status"]
        == "REVOKED"
    )

    after_assignment = sessions.issue_session(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "requested_scopes": ["document:read"],
        }
    )
    role_update = service.upsert_role(
        tenant_id="tenant-a",
        role_id="editor",
        payload={
            "scopes": ["document:read", "document:write"],
            "expected_revision": 1,
        },
        context=CONTEXT,
    )
    assert role_update["revoked_session_count"] == 1
    assert sessions.sessions[after_assignment["session"]["session_id"]]["status"] == "REVOKED"
    assert repository.events[-1]["details"]["revoked_session_count"] == 1


def test_group_update_and_member_mutation_cover_affected_subjects() -> None:
    service, _, sessions, _ = _stack()
    _seed(service)
    issued = sessions.issue_session(
        {"tenant_id": "tenant-a", "subject_id": "user-a"}
    )
    group = service.upsert_group(
        tenant_id="tenant-a",
        group_id="engineering",
        payload={"status": "DISABLED", "expected_revision": 1},
        context=CONTEXT,
    )
    assert group["revoked_session_count"] == 1
    assert sessions.sessions[issued["session"]["session_id"]]["status"] == "REVOKED"

    issued = sessions.issue_session(
        {"tenant_id": "tenant-a", "subject_id": "user-a"}
    )
    member = service.upsert_group_member(
        tenant_id="tenant-a",
        group_id="engineering",
        subject_id="user-a",
        payload={"status": "DISABLED", "expected_revision": 1},
        context=CONTEXT,
    )
    assert member["revoked_session_count"] == 1


def test_routes_enforce_admin_and_read_scopes() -> None:
    _, _, _, client = _stack()
    role_path = "/internal/v1/auth/tenants/tenant-a/roles/editor"
    role_payload = {"scopes": ["document:read"], "expected_revision": 0}
    assert client.put(role_path, json=role_payload).status_code == 401
    assert client.put(
        role_path,
        json=role_payload,
        headers=_headers(OA_AUTHORIZATION_READ_SCOPE),
    ).status_code == 403
    accepted = client.put(
        role_path,
        json=role_payload,
        headers=_headers(OA_AUTHORIZATION_ADMIN_SCOPE),
    )
    assert accepted.status_code == 200
    assert accepted.json()["response_schema_version"] == "oa_authz_mutation_response.v1"
    assert accepted.json()["request_id"] == "request-1237"

    effective_path = (
        "/internal/v1/auth/tenants/tenant-a/subjects/user-a/authorization"
    )
    assert client.get(
        effective_path,
        headers=_headers(OA_AUTHORIZATION_ADMIN_SCOPE),
    ).status_code == 403
    effective = client.get(
        effective_path,
        headers=_headers(OA_AUTHORIZATION_READ_SCOPE),
    )
    assert effective.status_code == 200
    assert effective.json()["authorization"]["roles"] == ["employee"]


def test_routes_cover_group_member_role_events_and_failures() -> None:
    _, _, _, client = _stack()
    admin = _headers(OA_AUTHORIZATION_ADMIN_SCOPE)
    reader = _headers(OA_AUTHORIZATION_READ_SCOPE)
    assert client.put(
        "/internal/v1/auth/tenants/tenant-a/groups/engineering",
        json={"expected_revision": 0},
        headers=admin,
    ).status_code == 200
    assert client.put(
        "/internal/v1/auth/tenants/tenant-a/groups/engineering/members/user-a",
        json={"expected_revision": 0},
        headers=admin,
    ).status_code == 200
    assert client.put(
        "/internal/v1/auth/tenants/tenant-a/roles/editor",
        json={"scopes": ["document:read"], "expected_revision": 0},
        headers=admin,
    ).status_code == 200
    assert client.put(
        "/internal/v1/auth/tenants/tenant-a/groups/engineering/roles/editor",
        json={"expected_revision": 0},
        headers=admin,
    ).status_code == 200

    events_path = "/internal/v1/auth/tenants/tenant-a/authorization-events"
    events = client.get(events_path, headers=reader)
    assert events.status_code == 200
    assert events.json()["count"] == 4
    assert client.get(f"{events_path}?limit=0", headers=reader).status_code == 400

    stale = client.put(
        "/internal/v1/auth/tenants/tenant-a/roles/editor",
        json={"scopes": ["document:write"], "expected_revision": 0},
        headers=admin,
    )
    assert stale.status_code == 409
    unsafe = client.put(
        "/internal/v1/auth/tenants/tenant-a/groups/engineering",
        json={"expected_revision": 1, "password": "private"},
        headers=admin,
    )
    assert unsafe.status_code == 400
    assert unsafe.json()["error_code"] == "oa.authorization_payload_invalid"


def test_effective_read_reports_missing_and_registry_failure() -> None:
    service, repository, _, client = _stack()
    missing = client.get(
        "/internal/v1/auth/tenants/tenant-a/subjects/missing/authorization",
        headers=_headers(OA_AUTHORIZATION_READ_SCOPE),
    )
    assert missing.status_code == 404

    class FailingMemberships:
        def get_membership(self, **_kwargs):
            raise OaMembershipError(503, "oa.membership_unavailable", "unavailable")

    failing = OaAuthorizationService(
        repository,
        OaEffectiveAuthorizationResolver(repository),
        FailingMemberships(),  # type: ignore[arg-type]
    )
    with pytest.raises(OaAuthorizationError) as caught:
        failing.effective_authorization(tenant_id="tenant-a", subject_id="user-a")
    assert caught.value.status_code == 503


def test_payload_identity_is_path_authoritative() -> None:
    service, _, _, _ = _stack()
    with pytest.raises(OaAuthorizationError, match="unsupported"):
        service.upsert_role(
            tenant_id="tenant-a",
            role_id="editor",
            payload={
                "tenant_id": "tenant-b",
                "scopes": ["document:read"],
            },
            context=CONTEXT,
        )
