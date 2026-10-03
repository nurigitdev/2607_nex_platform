import pytest

from nex_oa.authorization import OaAuthorizationError
from nex_oa.authorization_repository import InMemoryOaAuthorizationRepository
from nex_oa.authorization_resolver import (
    OaEffectiveAuthorizationResolver,
    require_effective_scopes,
    resolve_effective_authorization,
)
from nex_oa.memberships import InMemoryOaTenantMembershipRegistry
from nex_oa.sessions import InMemoryOaSessionRegistry, OaSessionError


CONTEXT = {
    "actor_ref": "nex.service:test",
    "request_id": "req",
    "trace_id": "trace",
}


def _membership(status: str = "ACTIVE") -> dict:
    return {
        "tenant_id": "tenant-a",
        "subject_id": "user-a",
        "status": status,
        "revision": 3,
        "roles": ["employee"],
        "scopes": ["user:session"],
    }


def _inputs() -> dict:
    return {
        "roles": [
            {
                "tenant_id": "tenant-a",
                "role_id": "editor",
                "status": "ACTIVE",
                "revision": 2,
                "scopes": ["doc:read", "doc:write"],
            },
            {
                "tenant_id": "tenant-a",
                "role_id": "disabled",
                "status": "DISABLED",
                "revision": 1,
                "scopes": ["admin:all"],
            },
            {
                "tenant_id": "tenant-b",
                "role_id": "foreign",
                "status": "ACTIVE",
                "revision": 1,
                "scopes": ["admin:all"],
            },
        ],
        "groups": [
            {
                "tenant_id": "tenant-a",
                "group_id": "engineering",
                "status": "ACTIVE",
                "revision": 4,
            },
            {
                "tenant_id": "tenant-a",
                "group_id": "disabled",
                "status": "DISABLED",
                "revision": 1,
            },
        ],
        "group_members": [
            {
                "tenant_id": "tenant-a",
                "group_id": "engineering",
                "subject_id": "user-a",
                "status": "ACTIVE",
            },
            {
                "tenant_id": "tenant-a",
                "group_id": "disabled",
                "subject_id": "user-a",
                "status": "ACTIVE",
            },
            {
                "tenant_id": "tenant-b",
                "group_id": "engineering",
                "subject_id": "user-a",
                "status": "ACTIVE",
            },
        ],
        "group_roles": [
            {
                "tenant_id": "tenant-a",
                "group_id": "engineering",
                "role_id": "editor",
                "status": "ACTIVE",
            },
            {
                "tenant_id": "tenant-a",
                "group_id": "engineering",
                "role_id": "disabled",
                "status": "ACTIVE",
            },
            {
                "tenant_id": "tenant-a",
                "group_id": "disabled",
                "role_id": "editor",
                "status": "ACTIVE",
            },
        ],
    }


def test_resolver_composes_direct_and_active_group_grants() -> None:
    result = resolve_effective_authorization(_membership(), inputs=_inputs())

    assert result["roles"] == ("editor", "employee")
    assert result["scopes"] == ("doc:read", "doc:write", "user:session")
    assert result["group_ids"] == ("engineering",)
    assert result["unresolved_direct_roles"] == ("employee",)
    assert len(result["revision_hash"]) == 64
    assert result["source_counts"]["group_role_count"] == 1
    require_effective_scopes(result, ["doc:read", "user:session"])


def test_resolver_fails_closed_for_inactive_invalid_and_missing_scope() -> None:
    with pytest.raises(OaAuthorizationError, match="active membership"):
        resolve_effective_authorization(_membership("DISABLED"), inputs=_inputs())
    with pytest.raises(OaAuthorizationError, match="roles must"):
        resolve_effective_authorization(
            {**_membership(), "roles": "employee"},
            inputs=_inputs(),
        )
    with pytest.raises(OaAuthorizationError, match="roles must"):
        resolve_effective_authorization(
            {**_membership(), "roles": ["employee", ""]},
            inputs=_inputs(),
        )
    with pytest.raises(OaAuthorizationError, match="required scope"):
        require_effective_scopes(
            resolve_effective_authorization(_membership(), inputs=_inputs()),
            ["admin:all"],
        )
    with pytest.raises(OaAuthorizationError, match="membership tenant"):
        resolve_effective_authorization(
            {"status": "ACTIVE", "roles": [], "scopes": []},
            inputs={},
        )


def test_nested_membership_shape_and_resolver_service() -> None:
    repository = InMemoryOaAuthorizationRepository()
    resolver = OaEffectiveAuthorizationResolver(repository)
    assert resolver.resolve(_membership())["roles"] == ("employee",)
    result = resolver.resolve({"membership": _membership()})
    assert result["roles"] == ("employee",)
    with pytest.raises(OaAuthorizationError, match="object"):
        resolver.resolve({"membership": []})
    with pytest.raises(OaAuthorizationError, match="active membership"):
        resolver.resolve({"membership": _membership("DISABLED")})


def test_session_uses_effective_scopes_and_preserves_legacy_default() -> None:
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
    repository.upsert_role(
        {
            "tenant_id": "tenant-a",
            "role_id": "editor",
            "scopes": ["doc:read"],
        },
        context=CONTEXT,
    )
    repository.upsert_group(
        {"tenant_id": "tenant-a", "group_id": "engineering"},
        context=CONTEXT,
    )
    repository.upsert_group_member(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "subject_id": "user-a",
        },
        context=CONTEXT,
    )
    repository.upsert_group_role(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "role_id": "editor",
        },
        context=CONTEXT,
    )
    hardened = InMemoryOaSessionRegistry(
        membership_registry=memberships,
        authorization_resolver=OaEffectiveAuthorizationResolver(repository),
    )
    session = hardened.issue_session(
        {
            "tenant_id": "tenant-a",
            "subject_id": "user-a",
            "requested_scopes": ["doc:read"],
        }
    )["session"]
    assert session["roles"] == ["editor", "employee"]
    assert session["scopes"] == ["doc:read"]

    compatible = InMemoryOaSessionRegistry(membership_registry=memberships)
    assert compatible.issue_session(
        {"tenant_id": "tenant-a", "subject_id": "user-a"}
    )["session"]["scopes"] == ["user:session"]
    with pytest.raises(OaSessionError, match="not granted"):
        compatible.issue_session(
            {
                "tenant_id": "tenant-a",
                "subject_id": "user-a",
                "requested_scopes": ["doc:read"],
            }
        )
