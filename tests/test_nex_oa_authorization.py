import pytest

from nex_oa.authorization import (
    OaAuthorizationError,
    normalize_authorization_id,
    normalize_authorization_metadata,
    normalize_authorization_scopes,
    normalize_authorization_status,
    plan_group_member_upsert,
    plan_group_role_upsert,
    plan_group_upsert,
    plan_role_upsert,
)


def test_role_and_group_plans_are_normalized_and_revisioned() -> None:
    role = plan_role_upsert(
        {
            "tenant_id": " tenant-a ",
            "role_id": " Editor.Role ",
            "display_name": " Editor ",
            "description": " Can edit ",
            "scopes": ["Document:Write", "document:read", "document:read"],
            "metadata": {"source": "admin"},
            "expected_revision": 0,
        }
    )
    group = plan_group_upsert(
        {
            "tenant_id": "tenant-a",
            "group_id": "Engineering.Team",
            "description": " ",
            "expected_revision": 0,
        }
    )

    assert role["role_id"] == "editor.role"
    assert role["scopes"] == ("document:read", "document:write")
    assert role["revision"] == 1
    assert group["group_id"] == "engineering.team"
    assert group["display_name"] == "engineering.team"
    assert group["description"] is None


def test_assignment_plans_preserve_tenant_scoped_identity() -> None:
    member = plan_group_member_upsert(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "subject_id": "user-a",
            "status": "disabled",
            "expected_revision": 0,
        }
    )
    assignment = plan_group_role_upsert(
        {
            "tenant_id": "tenant-a",
            "group_id": "engineering",
            "role_id": "editor",
            "expected_revision": 0,
        }
    )

    assert member["status"] == "DISABLED"
    assert member["subject_id"] == "user-a"
    assert assignment["status"] == "ACTIVE"
    assert assignment["role_id"] == "editor"


def test_update_requires_matching_revision_and_immutable_identity() -> None:
    current = plan_role_upsert(
        {
            "tenant_id": "tenant-a",
            "role_id": "editor",
            "scopes": ["document:read"],
            "expected_revision": 0,
        }
    )
    updated = plan_role_upsert(
        {
            "tenant_id": "tenant-a",
            "role_id": "editor",
            "scopes": ["document:write"],
            "expected_revision": 1,
        },
        current=current,
    )
    assert updated["previous_revision"] == 1
    assert updated["revision"] == 2

    with pytest.raises(OaAuthorizationError, match="expected_revision") as conflict:
        plan_role_upsert({**updated, "expected_revision": 0}, current=updated)
    assert conflict.value.status_code == 409

    with pytest.raises(OaAuthorizationError, match="immutable"):
        plan_role_upsert(
            {
                "tenant_id": "tenant-b",
                "role_id": "editor",
                "scopes": ["document:read"],
                "expected_revision": 1,
            },
            current=current,
        )


@pytest.mark.parametrize("value", [None, 1, "x", "A", "has space", "a" * 65])
def test_authorization_id_rejects_invalid_values(value) -> None:
    with pytest.raises(OaAuthorizationError):
        normalize_authorization_id(value, field_name="role_id")


@pytest.mark.parametrize("value", [None, 1, "pending"])
def test_authorization_status_rejects_invalid_values(value) -> None:
    with pytest.raises(OaAuthorizationError):
        normalize_authorization_status(value)


@pytest.mark.parametrize(
    "value",
    [None, "document:read", [], [1], ["invalid"], ["document:"]],
)
def test_scope_validation_rejects_invalid_values(value) -> None:
    with pytest.raises(OaAuthorizationError):
        normalize_authorization_scopes(value)


def test_metadata_rejects_private_fields_recursively() -> None:
    assert normalize_authorization_metadata(None) == {}
    assert normalize_authorization_metadata({"team": ["a"]}) == {"team": ["a"]}
    with pytest.raises(OaAuthorizationError, match="private"):
        normalize_authorization_metadata({"nested": [{"api_token": "private"}]})
    with pytest.raises(OaAuthorizationError, match="object"):
        normalize_authorization_metadata([])


@pytest.mark.parametrize("value", [True, -1, "01", "x"])
def test_revision_validation_rejects_invalid_values(value) -> None:
    with pytest.raises(OaAuthorizationError):
        plan_group_upsert(
            {
                "tenant_id": "tenant-a",
                "group_id": "engineering",
                "expected_revision": value,
            }
        )


def test_text_fields_are_bounded() -> None:
    with pytest.raises(OaAuthorizationError, match="display_name"):
        plan_group_upsert(
            {
                "tenant_id": "tenant-a",
                "group_id": "engineering",
                "display_name": " ",
            }
        )
    with pytest.raises(OaAuthorizationError, match="description"):
        plan_group_upsert(
            {
                "tenant_id": "tenant-a",
                "group_id": "engineering",
                "description": 3,
            }
        )
    with pytest.raises(OaAuthorizationError, match="at most"):
        plan_group_upsert(
            {
                "tenant_id": "tenant-a",
                "group_id": "engineering",
                "description": "x" * 513,
            }
        )
